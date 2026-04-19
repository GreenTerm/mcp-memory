from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .models import AppConfig, ProjectConfig


class ProjectRegistry:
    """Stores the global app config and known project entries."""

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path

    @property
    def config_path(self) -> Path:
        return self._config_path

    def load(self) -> AppConfig:
        if not self._config_path.exists():
            app_home = self._config_path.parent
            return AppConfig(
                app_home=app_home,
                registry_path=self._config_path,
                projects=[],
            )

        payload = json.loads(self._config_path.read_text(encoding="utf-8"))
        return AppConfig.from_dict(payload)

    def save(self, config: AppConfig) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def upsert_project(self, project: ProjectConfig) -> AppConfig:
        config = self.load()
        projects = [entry for entry in config.projects if entry.project_id != project.project_id]
        projects.append(project)
        updated = replace(config, projects=sorted(projects, key=lambda item: item.project_id))
        self.save(updated)
        return updated

    def remove_project(self, project_id: str) -> AppConfig:
        config = self.load()
        projects = [entry for entry in config.projects if entry.project_id != project_id]
        updated = replace(config, projects=projects)
        self.save(updated)
        return updated

    def get_project(self, project_id: str) -> ProjectConfig | None:
        config = self.load()
        for project in config.projects:
            if project.project_id == project_id:
                return project
        return None

    def list_projects(self) -> list[ProjectConfig]:
        return self.load().projects
