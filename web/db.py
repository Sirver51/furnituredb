"""Read-only connection to furniture.db (loads sqlite-vec, no schema writes).

The DB session owns ingestion/embedding (writes via db.connection.get_connection,
which also applies schema.sql). This module never writes -- opened in SQLite's
read-only URI mode so it can run alongside the writer safely.
"""

import sqlite3
from pathlib import Path

import sqlite_vec

DB_PATH = Path(__file__).resolve().parent.parent / "furniture.db"


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    return con
