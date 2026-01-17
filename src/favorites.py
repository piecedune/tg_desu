from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


class FavoritesStore:
    def __init__(self, db_path: str = "favorites.db") -> None:
        self.db_path = Path(db_path)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS favorites (
                    user_id INTEGER NOT NULL,
                    manga_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    cover TEXT,
                    PRIMARY KEY (user_id, manga_id)
                )
                """
            )
            conn.commit()

    def add(self, user_id: int, manga_id: int, title: str, cover: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO favorites (user_id, manga_id, title, cover)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, manga_id, title, cover),
            )
            conn.commit()

    def remove(self, user_id: int, manga_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM favorites WHERE user_id = ? AND manga_id = ?",
                (user_id, manga_id),
            )
            conn.commit()

    def list(self, user_id: int) -> Iterable[tuple[int, str, str | None]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT manga_id, title, cover FROM favorites WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return rows

    def has(self, user_id: int, manga_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM favorites WHERE user_id = ? AND manga_id = ?",
                (user_id, manga_id),
            ).fetchone()
        return row is not None
