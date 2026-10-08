"""Verified SQLite backup and restore operations."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def verify_database(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(path) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise ValueError("SQLite integrity check failed")


def backup_database(source: Path, destination: Path) -> None:
    """Create a consistent SQLite backup and verify the resulting database."""
    verify_database(source)
    if source.resolve() == destination.resolve():
        raise ValueError("backup destination must differ from source")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with (
            sqlite3.connect(source) as source_connection,
            sqlite3.connect(temporary) as destination_connection,
        ):
            source_connection.backup(destination_connection)
        verify_database(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def restore_database(backup: Path, destination: Path) -> None:
    """Verify a backup and atomically restore it to a closed destination database."""
    verify_database(backup)
    backup_database(backup, destination)
