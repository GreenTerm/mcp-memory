from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ProjectConfig:
    project_id: str
    display_name: str
    project_root: Path
    database_path: Path
    attachments_dir: Path
    exports_dir: Path
    backups_dir: Path
    logs_dir: Path
    schema_path: Path = field(default_factory=lambda: Path("schema.json"))
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 9876
    write_mode: str = "confirm"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key, value in payload.items():
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ProjectConfig":
        return cls(
            project_id=str(payload["project_id"]),
            display_name=str(payload["display_name"]),
            project_root=Path(str(payload["project_root"])),
            database_path=Path(str(payload["database_path"])),
            attachments_dir=Path(str(payload["attachments_dir"])),
            exports_dir=Path(str(payload["exports_dir"])),
            backups_dir=Path(str(payload["backups_dir"])),
            logs_dir=Path(str(payload["logs_dir"])),
            schema_path=Path(str(payload.get("schema_path", Path(str(payload["project_root"])) / "schema.json"))),
            http_host=str(payload.get("http_host", "127.0.0.1")),
            http_port=int(payload.get("http_port", 8765)),
            mcp_host=str(payload.get("mcp_host", "127.0.0.1")),
            mcp_port=int(payload.get("mcp_port", 9876)),
            write_mode=str(payload.get("write_mode", "confirm")),
        )


@dataclass(slots=True)
class AppConfig:
    app_home: Path
    registry_path: Path
    projects: list[ProjectConfig] = field(default_factory=list)
    base_url: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "app_home": str(self.app_home),
            "registry_path": str(self.registry_path),
            "base_url": self.base_url,
            "projects": [project.to_dict() for project in self.projects],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "AppConfig":
        projects = [
            ProjectConfig.from_dict(project_payload)
            for project_payload in payload.get("projects", [])
        ]
        return cls(
            app_home=Path(str(payload["app_home"])),
            registry_path=Path(str(payload["registry_path"])),
            projects=projects,
            base_url=str(payload.get("base_url", "")),
        )
