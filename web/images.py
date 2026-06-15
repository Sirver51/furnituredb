"""Resolve image rows to on-disk files under sites/<site>/<local_path>."""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def resolve_image_path(con: sqlite3.Connection, image_id: int) -> Path | None:
    row = con.execute(
        "SELECT i.local_path, p.site FROM image i JOIN product p ON p.id = i.product_id WHERE i.id = ?",
        (image_id,),
    ).fetchone()
    if row is None or not row["local_path"]:
        return None

    path = ROOT / "sites" / row["site"] / row["local_path"].replace("\\", "/")
    return path if path.exists() else None
