"""Storage layer for SQLite-backed project data."""

from .database import Database, open_database
from .migrations import bootstrap_project_database

__all__ = [
    "Database",
    "bootstrap_project_database",
    "open_database",
]

