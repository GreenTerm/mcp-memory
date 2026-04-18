from __future__ import annotations

import os
from pathlib import Path


def resolve_app_home(explicit_path: str | Path | None = None) -> Path:
    if explicit_path is not None:
        return Path(explicit_path).expanduser().resolve()

    env_path = os.environ.get("MCP_MEMORY_HOME")
    if env_path:
        return Path(env_path).expanduser().resolve()

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return (Path(local_app_data) / "mcp-memory").resolve()

    return (Path.cwd() / ".mcp-memory").resolve()


def resolve_registry_path(app_home: Path) -> Path:
    return app_home / "app_config.json"

