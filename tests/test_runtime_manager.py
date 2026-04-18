from __future__ import annotations

import subprocess
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from mcp_memory.config import ProjectConfig
from mcp_memory.runtime import ProjectRuntimeManager


@dataclass
class _ManagedEntryStub:
    project: ProjectConfig
    status: str
    reason: str
    http_process: object
    mcp_process: object

    def info(self):
        return mock.Mock(status=self.status, managed=True)


def _project() -> ProjectConfig:
    root = Path("C:/tmp/project")
    return ProjectConfig(
        project_id="p1",
        display_name="Project One",
        project_root=root,
        database_path=root / "project.db",
        attachments_dir=root / "attachments",
        exports_dir=root / "exports",
        backups_dir=root / "backups",
        logs_dir=root / "logs",
        http_port=12000,
        mcp_port=12001,
    )


class RuntimeManagerTests(unittest.TestCase):
    def test_start_project_returns_existing_running_managed_project(self) -> None:
        manager = ProjectRuntimeManager(Path("C:/tmp/app"))
        project = _project()
        http_process = mock.Mock(pid=111)
        http_process.poll.return_value = None
        mcp_process = mock.Mock(pid=222)
        mcp_process.poll.return_value = None
        manager._managed[project.project_id] = mock.Mock(
            project=project,
            status="running",
            reason="ready",
            http_process=http_process,
            mcp_process=mcp_process,
            info=mock.Mock(return_value=mock.Mock(status="running", managed=True, http_pid=111, mcp_pid=222)),
        )
        result = manager.start_project(project)
        self.assertEqual(result.status, "running")
        self.assertTrue(result.managed)

    def test_start_project_marks_running(self) -> None:
        manager = ProjectRuntimeManager(Path("C:/tmp/app"))
        project = _project()
        http_process = mock.Mock(pid=111)
        http_process.poll.return_value = None
        mcp_process = mock.Mock(pid=222)
        mcp_process.poll.return_value = None
        with mock.patch.object(manager, "_spawn_project_process", side_effect=[http_process, mcp_process]):
            with mock.patch("mcp_memory.runtime._probe_health", side_effect=[True, True]):
                result = manager.start_project(project)
        self.assertEqual(result.status, "running")
        self.assertTrue(result.managed)
        self.assertEqual(result.http_pid, 111)
        self.assertEqual(result.mcp_pid, 222)

    def test_start_project_marks_failed_when_health_never_comes_up(self) -> None:
        manager = ProjectRuntimeManager(Path("C:/tmp/app"), readiness_timeout_seconds=0.01, poll_interval_seconds=0.001)
        project = _project()
        http_process = mock.Mock(pid=111)
        http_process.poll.return_value = None
        mcp_process = mock.Mock(pid=222)
        mcp_process.poll.return_value = None
        with mock.patch.object(manager, "_spawn_project_process", side_effect=[http_process, mcp_process]):
            with mock.patch("mcp_memory.runtime._probe_health", return_value=False):
                result = manager.start_project(project)
        self.assertEqual(result.status, "failed")
        http_process.terminate.assert_called()
        mcp_process.terminate.assert_called()

    def test_stop_project_terminates_managed_processes(self) -> None:
        manager = ProjectRuntimeManager(Path("C:/tmp/app"))
        project = _project()
        http_process = mock.Mock(pid=111)
        http_process.poll.return_value = None
        mcp_process = mock.Mock(pid=222)
        mcp_process.poll.return_value = None
        with mock.patch.object(manager, "_spawn_project_process", side_effect=[http_process, mcp_process]):
            with mock.patch("mcp_memory.runtime._probe_health", side_effect=[True, True]):
                manager.start_project(project)
        result = manager.stop_project(project.project_id)
        self.assertEqual(result.status, "stopped")
        http_process.terminate.assert_called()
        mcp_process.terminate.assert_called()

    def test_stop_project_for_unmanaged_project_returns_stopped(self) -> None:
        manager = ProjectRuntimeManager(Path("C:/tmp/app"))
        result = manager.stop_project("missing-project")
        self.assertEqual(result.status, "stopped")
        self.assertFalse(result.managed)

    def test_restart_project_restarts_managed_processes(self) -> None:
        manager = ProjectRuntimeManager(Path("C:/tmp/app"))
        project = _project()
        http_one = mock.Mock(pid=111)
        http_one.poll.return_value = None
        mcp_one = mock.Mock(pid=222)
        mcp_one.poll.return_value = None
        http_two = mock.Mock(pid=333)
        http_two.poll.return_value = None
        mcp_two = mock.Mock(pid=444)
        mcp_two.poll.return_value = None
        with mock.patch.object(manager, "_spawn_project_process", side_effect=[http_one, mcp_one, http_two, mcp_two]):
            with mock.patch("mcp_memory.runtime._probe_health", side_effect=[True, True, True, True]):
                manager.start_project(project)
                result = manager.restart_project(project)
        self.assertEqual(result.status, "running")
        self.assertEqual(result.http_pid, 333)
        self.assertEqual(result.mcp_pid, 444)
        http_one.terminate.assert_called()
        mcp_one.terminate.assert_called()

    def test_get_project_runtime_reports_external_running(self) -> None:
        manager = ProjectRuntimeManager(Path("C:/tmp/app"))
        with mock.patch("mcp_memory.runtime._probe_health", side_effect=[True, True]):
            result = manager.get_project_runtime(_project())
        self.assertEqual(result.status, "running")
        self.assertFalse(result.managed)

    def test_get_project_runtime_marks_failed_when_managed_processes_exit(self) -> None:
        manager = ProjectRuntimeManager(Path("C:/tmp/app"))
        project = _project()
        http_process = mock.Mock(pid=111)
        http_process.poll.return_value = 1
        mcp_process = mock.Mock(pid=222)
        mcp_process.poll.return_value = 1
        manager._managed[project.project_id] = _ManagedEntryStub(
            project=project,
            status="running",
            reason="ready",
            http_process=http_process,
            mcp_process=mcp_process,
        )
        result = manager.get_project_runtime(project)
        self.assertEqual(result.status, "failed")

    def test_stop_managed_kills_process_after_timeout(self) -> None:
        manager = ProjectRuntimeManager(Path("C:/tmp/app"))
        process = mock.Mock()
        process.poll.side_effect = [None, None]
        process.wait.side_effect = [subprocess.TimeoutExpired(cmd="x", timeout=5), None]
        managed = mock.Mock(http_process=process, mcp_process=None)
        manager._stop_managed(managed, force=True)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()

    def test_shutdown_all_stops_managed_projects(self) -> None:
        manager = ProjectRuntimeManager(Path("C:/tmp/app"))
        project = _project()
        http_process = mock.Mock(pid=111)
        http_process.poll.return_value = None
        mcp_process = mock.Mock(pid=222)
        mcp_process.poll.return_value = None
        with mock.patch.object(manager, "_spawn_project_process", side_effect=[http_process, mcp_process]):
            with mock.patch("mcp_memory.runtime._probe_health", side_effect=[True, True]):
                manager.start_project(project)
        manager.shutdown_all()
        http_process.terminate.assert_called()
        mcp_process.terminate.assert_called()


if __name__ == "__main__":
    unittest.main()
