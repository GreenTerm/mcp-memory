from __future__ import annotations

import json
import logging
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from mcp_memory.config import ProjectConfig, ProjectRegistry
from mcp_memory.logging_utils import get_logger, log_event
from mcp_memory.services.projects import validate_project_id
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
        target_existed = project_root.exists()
        if target_existed and not project_root.is_dir():
            raise ValueError("project_root must point to a directory")
        if target_existed and any(project_root.iterdir()):
            raise ValueError("project_root already exists and is not empty")

        with zipfile.ZipFile(input_path, "r") as archive:
            project_members = self._preflight_project_members(archive)
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            source_project = manifest["project"]
            target_project_id = str(project_id or source_project["project_id"])
            validate_project_id(target_project_id)
            if self._registry.get_project(target_project_id) is not None:
                raise ValueError(f"project_id already exists: {target_project_id}")

            project_root.parent.mkdir(parents=True, exist_ok=True)
            temp_root = Path(tempfile.mkdtemp(prefix=f".{project_root.name}.restore-", dir=project_root.parent))
            published = False
            try:
                for member, relative in project_members:
                    destination = temp_root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member, "r") as source_file:
                        destination.write_bytes(source_file.read())

                temp_config = self._restored_config(
                    source_project=source_project,
                    project_id=target_project_id,
                    display_name=display_name,
                    project_root=temp_root,
                    http_port=http_port,
                    mcp_port=mcp_port,
                    write_mode=write_mode,
                )
                for directory in (
                    temp_config.attachments_dir,
                    temp_config.exports_dir,
                    temp_config.backups_dir,
                    temp_config.logs_dir,
                ):
                    directory.mkdir(parents=True, exist_ok=True)
                if temp_config.project_id != str(source_project["project_id"]):
                    self._rewrite_project_id(
                        temp_config.database_path,
                        str(source_project["project_id"]),
                        temp_config.project_id,
                    )

                if project_root.exists():
                    project_root.rmdir()
                temp_root.rename(project_root)
                published = True

                config = self._restored_config(
                    source_project=source_project,
                    project_id=target_project_id,
                    display_name=display_name,
                    project_root=project_root,
                    http_port=http_port,
                    mcp_port=mcp_port,
                    write_mode=write_mode,
                )
                self._registry.upsert_project(config)
            except Exception:
                if temp_root.exists():
                    shutil.rmtree(temp_root, ignore_errors=True)
                if published and project_root.exists():
                    shutil.rmtree(project_root, ignore_errors=True)
                if target_existed and not project_root.exists():
                    project_root.mkdir(parents=True, exist_ok=True)
                raise

        log_event(
            self._logger,
            logging.INFO,
            "project_restored",
            project_id=config.project_id,
            input_path=input_path,
            project_root=project_root,
        )
        return config

    def _preflight_project_members(self, archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, Path]]:
        project_members: list[tuple[zipfile.ZipInfo, Path]] = []
        seen_paths: set[str] = set()
        manifest_seen = False

        for member in archive.infolist():
            name = member.filename
            path = PurePosixPath(name)
            normalized = "/".join(part.casefold() for part in path.parts)
            if normalized in seen_paths:
                raise ValueError(f"Duplicate backup member path: {name}")
            seen_paths.add(normalized)

            if name == "manifest.json":
                manifest_seen = True
                continue
            if "\\" in name or path.is_absolute() or not name.startswith("project/"):
                raise ValueError(f"Unsafe backup member path: {name}")
            relative = path.relative_to("project")
            if (
                not relative.parts
                or relative.is_absolute()
                or ".." in relative.parts
                or PureWindowsPath(*relative.parts).drive
                or any(":" in part for part in relative.parts)
            ):
                raise ValueError(f"Unsafe backup member path: {name}")
            if member.is_dir():
                raise ValueError(f"Backup member must be a project file: {name}")
            project_members.append((member, Path(*relative.parts)))

        if not manifest_seen:
            raise ValueError("Backup manifest is missing")
        return project_members

    def _restored_config(
        self,
        *,
        source_project: dict[str, Any],
        project_id: str,
        display_name: str | None,
        project_root: Path,
        http_port: int | None,
        mcp_port: int | None,
        write_mode: str | None,
    ) -> ProjectConfig:
        return ProjectConfig(
            project_id=project_id,
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
