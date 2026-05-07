from __future__ import annotations

import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp_memory.config import ProjectConfig, ProjectRegistry
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.storage import open_database


class ProjectArchiveService:
    def __init__(self, registry: ProjectRegistry) -> None:
        self._registry = registry
        self._logger = get_logger("services")

    def create_backup(self, project: ProjectConfig, output_path: Path | None = None) -> dict[str, Any]:
        final_path = output_path or self._default_backup_path(project)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "project": {
                "project_id": project.project_id,
                "display_name": project.display_name,
                "http_host": project.http_host,
                "http_port": project.http_port,
                "mcp_host": project.mcp_host,
                "mcp_port": project.mcp_port,
                "write_mode": project.write_mode,
                "schema_path": "schema.json",
            },
            "created_at": datetime.now().isoformat(),
        }

        file_count = 0
        with zipfile.ZipFile(final_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for path in sorted(project.project_root.rglob("*")):
                if path.is_dir():
                    continue
                if path.resolve() == final_path.resolve():
                    continue
                try:
                    relative = path.relative_to(project.backups_dir)
                except ValueError:
                    relative = None
                if relative is not None:
                    continue
                archive.write(path, Path("project") / path.relative_to(project.project_root))
                file_count += 1

        log_event(
            self._logger,
            logging.INFO,
            "project_backed_up",
            project_id=project.project_id,
            output_path=final_path,
            file_count=file_count,
        )
        return {
            "output_path": str(final_path),
            "file_count": file_count,
        }

    def restore_backup(
        self,
        input_path: Path,
        project_root: Path,
        project_id: str | None = None,
        display_name: str | None = None,
        http_port: int | None = None,
        mcp_port: int | None = None,
        write_mode: str | None = None,
    ) -> ProjectConfig:
        with zipfile.ZipFile(input_path, "r") as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            source_project = manifest["project"]
            target_project_id = str(project_id or source_project["project_id"])
            if self._registry.get_project(target_project_id) is not None:
                raise ValueError(f"project_id already exists: {target_project_id}")

            project_root.mkdir(parents=True, exist_ok=True)
            for member in archive.namelist():
                if member == "manifest.json":
                    continue
                if not member.startswith("project/"):
                    continue
                relative = Path(member).relative_to("project")
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(f"Unsafe backup member path: {member}")
                destination = project_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source_file:
                    destination.write_bytes(source_file.read())

        config = ProjectConfig(
            project_id=target_project_id,
            display_name=str(display_name or source_project["display_name"]),
            project_root=project_root,
            database_path=project_root / "project.db",
            attachments_dir=project_root / "attachments",
            exports_dir=project_root / "exports",
            backups_dir=project_root / "backups",
            logs_dir=project_root / "logs",
            schema_path=project_root / str(source_project.get("schema_path", "schema.json")),
            http_host=str(source_project.get("http_host", "127.0.0.1")),
            http_port=int(http_port if http_port is not None else source_project.get("http_port", 8765)),
            mcp_host=str(source_project.get("mcp_host", "127.0.0.1")),
            mcp_port=int(mcp_port if mcp_port is not None else source_project.get("mcp_port", 9876)),
            write_mode=str(write_mode or source_project.get("write_mode", "confirm")),
        )
        for directory in (config.attachments_dir, config.exports_dir, config.backups_dir, config.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
        if config.project_id != str(source_project["project_id"]):
            self._rewrite_project_id(config.database_path, str(source_project["project_id"]), config.project_id)
        self._registry.upsert_project(config)
        log_event(
            self._logger,
            logging.INFO,
            "project_restored",
            project_id=config.project_id,
            input_path=input_path,
            project_root=project_root,
        )
        return config

    def _default_backup_path(self, project: ProjectConfig) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return project.backups_dir / f"{project.project_id}-{timestamp}.zip"

    def _rewrite_project_id(self, database_path: Path, old_project_id: str, new_project_id: str) -> None:
        tables = [
            "records",
            "functions",
            "structures",
            "hypotheses",
            "evidence",
            "attachments",
            "relations",
            "entity_facts",
            "tags",
            "entity_tags",
            "duplicate_candidates",
            "entity_versions",
            "audit_log",
            "pending_changes",
            "search_documents",
            "search_documents_fts",
        ]
        with open_database(database_path) as database:
            connection = database.transaction()
            for table in tables:
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
                    (table,),
                ).fetchone()
                if exists is None:
                    continue
                connection.execute(f"UPDATE {table} SET project_id = ? WHERE project_id = ?", (new_project_id, old_project_id))
            connection.commit()
