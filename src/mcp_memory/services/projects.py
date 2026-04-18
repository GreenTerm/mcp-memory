from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import logging

from mcp_memory.config import AppConfig, ProjectConfig, ProjectRegistry
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.storage import bootstrap_project_database, open_database


class ProjectService:
    """Creates and registers project workspaces."""

    def __init__(self, registry: ProjectRegistry) -> None:
        self._registry = registry
        self._logger = get_logger("services")

    def initialize_app(self) -> AppConfig:
        config = self._registry.load()
        self._registry.save(config)
        log_event(self._logger, logging.INFO, "app_initialized", app_home=config.app_home, project_count=len(config.projects))
        return config

    def create_project(
        self,
        project_id: str,
        display_name: str,
        project_root: Path,
        http_port: int,
        mcp_port: int,
        write_mode: str = "confirm",
    ) -> ProjectConfig:
        existing = self._registry.get_project(project_id)
        if existing is not None:
            raise ValueError(f"project_id already exists: {project_id}")

        if not project_id.strip():
            raise ValueError("project_id is required")
        if not display_name.strip():
            raise ValueError("display_name is required")
        if write_mode not in {"confirm", "auto"}:
            raise ValueError("write_mode must be one of: confirm, auto")
        if http_port <= 0 or mcp_port <= 0:
            raise ValueError("http_port and mcp_port must be positive integers")
        if http_port == mcp_port:
            raise ValueError("http_port and mcp_port must be different")
        if project_root.exists() and not project_root.is_dir():
            raise ValueError("project_root must point to a directory")
        if project_root.exists() and any(project_root.iterdir()):
            raise ValueError(
                "project_root already exists and is not empty. Home GUI create only supports a new workspace folder."
            )

        project_root.mkdir(parents=True, exist_ok=True)
        attachments_dir = project_root / "attachments"
        exports_dir = project_root / "exports"
        backups_dir = project_root / "backups"
        logs_dir = project_root / "logs"
        for directory in (attachments_dir, exports_dir, backups_dir, logs_dir):
            directory.mkdir(parents=True, exist_ok=True)

        config = ProjectConfig(
            project_id=project_id,
            display_name=display_name,
            project_root=project_root,
            database_path=project_root / "project.db",
            attachments_dir=attachments_dir,
            exports_dir=exports_dir,
            backups_dir=backups_dir,
            logs_dir=logs_dir,
            http_port=http_port,
            mcp_port=mcp_port,
            write_mode=write_mode,
        )

        database = open_database(config.database_path)
        try:
            bootstrap_project_database(database)
        finally:
            database.close()

        self._registry.upsert_project(config)
        log_event(
            self._logger,
            logging.INFO,
            "project_created",
            project_id=config.project_id,
            project_root=config.project_root,
            http_port=config.http_port,
            mcp_port=config.mcp_port,
            write_mode=config.write_mode,
        )
        return config

    def list_projects(self) -> list[ProjectConfig]:
        return self._registry.list_projects()

    def update_project(
        self,
        project_id: str,
        display_name: str,
        write_mode: str,
        http_host: str,
        http_port: int,
        mcp_host: str,
        mcp_port: int,
    ) -> ProjectConfig:
        existing = self._registry.get_project(project_id)
        if existing is None:
            raise ValueError(f"project_id not found: {project_id}")

        if not display_name.strip():
            raise ValueError("display_name is required")
        if write_mode not in {"confirm", "auto"}:
            raise ValueError("write_mode must be one of: confirm, auto")
        if not http_host.strip():
            raise ValueError("http_host is required")
        if not mcp_host.strip():
            raise ValueError("mcp_host is required")
        if http_port <= 0 or mcp_port <= 0:
            raise ValueError("http_port and mcp_port must be positive integers")
        if http_port > 65535 or mcp_port > 65535:
            raise ValueError("http_port and mcp_port must be between 1 and 65535")
        if http_port == mcp_port:
            raise ValueError("http_port and mcp_port must be different")

        updated = replace(
            existing,
            display_name=display_name.strip(),
            write_mode=write_mode,
            http_host=http_host.strip(),
            http_port=http_port,
            mcp_host=mcp_host.strip(),
            mcp_port=mcp_port,
        )
        self._registry.upsert_project(updated)
        log_event(
            self._logger,
            logging.INFO,
            "project_updated",
            project_id=updated.project_id,
            display_name=updated.display_name,
            http_host=updated.http_host,
            http_port=updated.http_port,
            mcp_host=updated.mcp_host,
            mcp_port=updated.mcp_port,
            write_mode=updated.write_mode,
        )
        return updated
