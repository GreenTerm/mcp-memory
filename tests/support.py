from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_memory.config import ProjectRegistry
from mcp_memory.logging_utils import shutdown_logging
from mcp_memory.services import ProjectService
from mcp_memory.storage import open_database


class ProjectSandbox:
    def __init__(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.app_home = self.root / "app_home"
        self.project_root = self.root / "project"
        self.registry = ProjectRegistry(self.app_home / "app_config.json")
        self.project_service = ProjectService(self.registry)
        self.project_service.initialize_app()
        self.project = self.project_service.create_project(
            project_id="test-project",
            display_name="Test Project",
            project_root=self.project_root,
            http_port=18765,
            mcp_port=19876,
            write_mode="confirm",
        )

    def open_database(self):
        return open_database(self.project.database_path)

    def cleanup(self) -> None:
        shutdown_logging()
        self._tmp.cleanup()
