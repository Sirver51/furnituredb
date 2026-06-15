"""VectorStore interface + sqlite-vec implementation.

vec0 virtual tables don't support `INSERT OR REPLACE` (raises a UNIQUE
constraint error on the primary key) -- upsert is delete-then-insert.
"""

from __future__ import annotations

import struct
from abc import ABC, abstractmethod

import sqlite_vec


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, id_: int, vector: list[float]) -> None: ...

    @abstractmethod
    def get(self, id_: int) -> list[float] | None: ...

    @abstractmethod
    def search(self, vector: list[float], k: int) -> list[tuple[int, float]]: ...


class SqliteVecStore(VectorStore):
    """vec0 table with schema `(<id_column> INTEGER PRIMARY KEY, embedding FLOAT[dim])`."""

    def __init__(self, con, table: str, id_column: str, dim: int):
        self._con = con
        self._table = table
        self._id_column = id_column
        self._dim = dim

    def upsert(self, id_: int, vector: list[float]) -> None:
        self._con.execute(f"DELETE FROM {self._table} WHERE {self._id_column} = ?", (id_,))
        self._con.execute(
            f"INSERT INTO {self._table} ({self._id_column}, embedding) VALUES (?, ?)",
            (id_, sqlite_vec.serialize_float32(vector)),
        )

    def get(self, id_: int) -> list[float] | None:
        row = self._con.execute(
            f"SELECT embedding FROM {self._table} WHERE {self._id_column} = ?", (id_,)
        ).fetchone()
        if row is None:
            return None
        return list(struct.unpack(f"{self._dim}f", row[0]))

    def search(self, vector: list[float], k: int) -> list[tuple[int, float]]:
        rows = self._con.execute(
            f"SELECT {self._id_column}, distance FROM {self._table} "
            f"WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (sqlite_vec.serialize_float32(vector), k),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]
