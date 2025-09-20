import os
import sqlite3
from contextlib import contextmanager
from typing import Iterable, List, Optional

from models import Run

_DB_DIRECTORY = os.path.join(os.path.dirname(__file__), 'data')
_DB_PATH = os.path.join(_DB_DIRECTORY, 'runs.db')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_enum INTEGER PRIMARY KEY AUTOINCREMENT,
    total_iterations INTEGER NOT NULL,
    run_name TEXT NOT NULL
);
"""


def _ensure_db_directory() -> None:
    os.makedirs(_DB_DIRECTORY, exist_ok=True)


@contextmanager
def _connection() -> Iterable[sqlite3.Connection]:
    _ensure_db_directory()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with _connection() as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def list_runs() -> List[Run]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT run_enum, total_iterations, run_name FROM runs ORDER BY run_enum"
        ).fetchall()
    return [Run(run_enum=row['run_enum'], total_iterations=row['total_iterations'], run_name=row['run_name']) for row in rows]


def get_run(run_enum: int) -> Optional[Run]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT run_enum, total_iterations, run_name FROM runs WHERE run_enum = ?",
            (run_enum,),
        ).fetchone()
    if row is None:
        return None
    return Run(run_enum=row['run_enum'], total_iterations=row['total_iterations'], run_name=row['run_name'])


def create_run(default_total_iterations: int = 50, default_run_name: str = "") -> Run:
    with _connection() as conn:
        cursor = conn.execute(
            "INSERT INTO runs (total_iterations, run_name) VALUES (?, ?)",
            (default_total_iterations, default_run_name),
        )
        conn.commit()
        run_enum = cursor.lastrowid
    return Run(run_enum=run_enum, total_iterations=default_total_iterations, run_name=default_run_name)


def update_total_iterations(run_enum: int, total_iterations: int) -> bool:
    with _connection() as conn:
        cursor = conn.execute(
            "UPDATE runs SET total_iterations = ? WHERE run_enum = ?",
            (total_iterations, run_enum),
        )
        conn.commit()
    return cursor.rowcount == 1


def update_run_name(run_enum: int, run_name: str) -> bool:
    with _connection() as conn:
        cursor = conn.execute(
            "UPDATE runs SET run_name = ? WHERE run_enum = ?",
            (run_name, run_enum),
        )
        conn.commit()
    return cursor.rowcount == 1
