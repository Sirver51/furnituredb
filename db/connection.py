"""SQLite connection helper: loads sqlite-vec and applies schema.sql."""

import sqlite3
from pathlib import Path

import sqlite_vec

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_DB_PATH = Path(__file__).parent.parent / "furniture.db"


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    # WAL + busy_timeout: multiple embed/ingest processes can run against the
    # same file concurrently without "database is locked" errors.
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=300000")
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return con
