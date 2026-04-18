from __future__ import annotations

from pathlib import Path

from .database import Database


def _sql_path() -> Path:
    return Path(__file__).resolve().parents[3] / "sql" / "migrations" / "001_initial.sql"


def bootstrap_project_database(database: Database) -> None:
    script = _sql_path().read_text(encoding="utf-8")
    database.connection.executescript(script)
    database.connection.commit()

