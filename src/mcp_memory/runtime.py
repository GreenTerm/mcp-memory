from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import error, request

from mcp_memory.config import ProjectConfig
from mcp_memory.logging_utils import get_logger, log_event


@dataclass(slots=True)
class ProjectRuntimeInfo:
    project_id: str
    status: str
    reason: str
    managed: bool
    http_pid: int | None = None
    mcp_pid: int | None = None


@dataclass(slots=True)
class _ManagedProjectProcesses:
    project: ProjectConfig
    status: str
    reason: str
    http_process: subprocess.Popen[str] | None = None
    mcp_process: subprocess.Popen[str] | None = None

    def info(self) -> ProjectRuntimeInfo:
        return ProjectRuntimeInfo(
            project_id=self.project.project_id,
            status=self.status,
            reason=self.reason,
            managed=True,
            http_pid=None if self.http_process is None else self.http_process.pid,
            mcp_pid=None if self.mcp_process is None else self.mcp_process.pid,
        )


class ProjectRuntimeManager:
    def __init__(
        self,
        app_home: Path,
        logger=None,
        python_executable: str | None = None,
        readiness_timeout_seconds: float = 8.0,
        poll_interval_seconds: float = 0.2,
    ) -> None:
        self._app_home = app_home
        self._logger = logger or get_logger("ui_home")
        self._python_executable = python_executable or sys.executable
        self._readiness_timeout_seconds = readiness_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._lock = threading.RLock()
        self._managed: dict[str, _ManagedProjectProcesses] = {}

    def start_project(self, project: ProjectConfig) -> ProjectRuntimeInfo:
        with self._lock:
            current = self._managed.get(project.project_id)
            if current is not None and current.status == "running" and self._processes_alive(current):
                return current.info()

            log_event(self._logger, logging.INFO, "project_start_requested", project_id=project.project_id)
            managed = _ManagedProjectProcesses(project=project, status="starting", reason="Starting project services.")
            self._managed[project.project_id] = managed

            try:
                managed.http_process = self._spawn_project_process(project, "run-http-api", project.http_host, project.http_port)
                managed.mcp_process = self._spawn_project_process(project, "run-mcp", project.mcp_host, project.mcp_port)
                self._wait_until_ready(managed)
                managed.status = "running"
                managed.reason = "Project HTTP and MCP services are running."
                log_event(
                    self._logger,
                    logging.INFO,
                    "project_started",
                    project_id=project.project_id,
                    http_pid=None if managed.http_process is None else managed.http_process.pid,
                    mcp_pid=None if managed.mcp_process is None else managed.mcp_process.pid,
                )
            except Exception as exc:
                managed.status = "failed"
                managed.reason = str(exc)
                self._stop_managed(managed, force=True)
                log_event(
                    self._logger,
                    logging.ERROR,
                    "project_failed",
                    project_id=project.project_id,
                    error=str(exc),
                )
            return managed.info()

    def stop_project(self, project_id: str) -> ProjectRuntimeInfo:
        with self._lock:
            current = self._managed.get(project_id)
            if current is None:
                return ProjectRuntimeInfo(project_id=project_id, status="stopped", reason="Project is not managed by home UI.", managed=False)

            log_event(self._logger, logging.INFO, "project_stop_requested", project_id=project_id)
            current.status = "stopped"
            current.reason = "Project services were stopped from home UI."
            self._stop_managed(current, force=True)
            log_event(
                self._logger,
                logging.INFO,
                "project_stopped",
                project_id=project_id,
                http_pid=None if current.http_process is None else current.http_process.pid,
                mcp_pid=None if current.mcp_process is None else current.mcp_process.pid,
            )
            return current.info()

    def restart_project(self, project: ProjectConfig) -> ProjectRuntimeInfo:
        with self._lock:
            log_event(self._logger, logging.INFO, "project_restart_requested", project_id=project.project_id)
        self.stop_project(project.project_id)
        return self.start_project(project)

    def get_project_runtime(self, project: ProjectConfig) -> ProjectRuntimeInfo:
        with self._lock:
            current = self._managed.get(project.project_id)
            if current is not None:
                if current.status == "running" and not self._processes_alive(current):
                    current.status = "failed"
                    current.reason = "Managed project processes exited unexpectedly."
                    log_event(self._logger, logging.ERROR, "project_failed", project_id=project.project_id, error=current.reason)
                return current.info()

        http_running = _probe_health(project.http_host, project.http_port)
        mcp_running = _probe_health(project.mcp_host, project.mcp_port)
        log_event(
            self._logger,
            logging.INFO,
            "project_probe",
            project_id=project.project_id,
            http_running=http_running,
            mcp_running=mcp_running,
        )
        if http_running and mcp_running:
            return ProjectRuntimeInfo(
                project_id=project.project_id,
                status="running",
                reason="Project services are already running outside home UI.",
                managed=False,
            )
        return ProjectRuntimeInfo(
            project_id=project.project_id,
            status="stopped",
            reason="Project services are not running yet.",
            managed=False,
        )

    def shutdown_all(self) -> None:
        with self._lock:
            for project_id, managed in list(self._managed.items()):
                log_event(self._logger, logging.INFO, "project_stop_requested", project_id=project_id)
                self._stop_managed(managed, force=True)
                managed.status = "stopped"
                managed.reason = "Stopped during home UI shutdown."
                log_event(self._logger, logging.INFO, "project_stopped", project_id=project_id)

    def _spawn_project_process(self, project: ProjectConfig, command: str, host: str, port: int) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [
                self._python_executable,
                "-X",
                "utf8",
                "-m",
                "mcp_memory.cli",
                "--app-home",
                str(self._app_home),
                "run-http-api" if command == "run-http-api" else "run-mcp",
                project.project_id,
                "--host",
                host,
                "--port",
                str(port),
            ],
            cwd=str(Path(__file__).resolve().parents[2]),
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _wait_until_ready(self, managed: _ManagedProjectProcesses) -> None:
        deadline = time.time() + self._readiness_timeout_seconds
        project = managed.project
        while time.time() < deadline:
            if not self._processes_alive(managed):
                raise RuntimeError("One of the managed project processes exited before becoming healthy.")
            if _probe_health(project.http_host, project.http_port) and _probe_health(project.mcp_host, project.mcp_port):
                return
            time.sleep(self._poll_interval_seconds)
        raise RuntimeError("Project services did not become healthy before timeout.")

    def _processes_alive(self, managed: _ManagedProjectProcesses) -> bool:
        return (
            managed.http_process is not None
            and managed.mcp_process is not None
            and managed.http_process.poll() is None
            and managed.mcp_process.poll() is None
        )

    def _stop_managed(self, managed: _ManagedProjectProcesses, force: bool) -> None:
        for process in (managed.http_process, managed.mcp_process):
            if process is None:
                continue
            if process.poll() is not None:
                continue
            process.terminate()
        for process in (managed.http_process, managed.mcp_process):
            if process is None:
                continue
            if process.poll() is not None:
                continue
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if force:
                    process.kill()
                    process.wait(timeout=5)


def _probe_health(host: str, port: int, timeout_seconds: float = 0.35) -> bool:
    url = f"http://{host}:{port}/health"
    try:
        with request.urlopen(url, timeout=timeout_seconds) as response:
            return response.status == 200
    except (error.URLError, TimeoutError, OSError):
        return False
