from __future__ import annotations

import sqlite3
from pathlib import Path


def _dict_factory(cursor: sqlite3.Cursor, row: tuple[object, ...]) -> dict[str, object]:
    return {description[0]: row[index] for index, description in enumerate(cursor.description)}


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = _dict_factory
        self.connection.execute("PRAGMA foreign_keys = ON;")
        self.connection.execute("PRAGMA journal_mode = WAL;")

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def transaction(self) -> sqlite3.Connection:
        return self.connection


def open_database(path: Path) -> Database:
    path.parent.mkdir(parents=True, exist_ok=True)
    return Database(path)
