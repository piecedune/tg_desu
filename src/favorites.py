from __future__ import annotations

import sqlite3
from datetime import datetime
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
            # Users table with more info
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_blocked INTEGER DEFAULT 0
                )
                """
            )
            # Favorites with timestamp
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS favorites (
                    user_id INTEGER NOT NULL,
                    manga_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    cover TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, manga_id)
                )
                """
            )
            # Reading history - track which chapters user read
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reading_history (
                    user_id INTEGER NOT NULL,
                    manga_id INTEGER NOT NULL,
                    chapter_id INTEGER NOT NULL,
                    chapter_num TEXT,
                    read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, manga_id, chapter_id)
                )
                """
            )
            # File cache - store Telegram file_id to avoid re-uploading
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_cache (
                    manga_id INTEGER NOT NULL,
                    chapter_id INTEGER NOT NULL,
                    format TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    file_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (manga_id, chapter_id, format)
                )
                """
            )
            # User settings
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    download_format TEXT DEFAULT 'pdf',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Manga view history (when user opens manga details)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS manga_history (
                    user_id INTEGER NOT NULL,
                    manga_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    cover TEXT,
                    viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, manga_id)
                )
                """
            )
            # Track last known chapter count for notifications
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS manga_chapter_count (
                    manga_id INTEGER PRIMARY KEY,
                    chapter_count INTEGER NOT NULL,
                    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # User notification settings
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_settings (
                    user_id INTEGER PRIMARY KEY,
                    notifications_enabled INTEGER DEFAULT 1
                )
                """
            )
            # Error log table for debugging
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS error_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    error_type TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    context TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Album cache - store file_ids for album pages
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS album_cache (
                    manga_id INTEGER NOT NULL,
                    chapter_id INTEGER NOT NULL,
                    batch_index INTEGER NOT NULL,
                    file_ids TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (manga_id, chapter_id, batch_index)
                )
                """
            )
            # Indexes for faster queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_user ON reading_history(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users(last_active)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_file_cache ON file_cache(manga_id, chapter_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_manga_history_user ON manga_history(user_id, viewed_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_error_log_time ON error_log(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_album_cache ON album_cache(manga_id, chapter_id)")
            conn.commit()

    # ========== User Methods ==========
    
    def add_user(
        self, 
        user_id: int, 
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None
    ) -> None:
        """Track or update a user in the database."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name, last_active)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = COALESCE(excluded.username, username),
                    first_name = COALESCE(excluded.first_name, first_name),
                    last_name = COALESCE(excluded.last_name, last_name),
                    last_active = CURRENT_TIMESTAMP
                """,
                (user_id, username, first_name, last_name),
            )
            conn.commit()

    def get_user_info(self, user_id: int) -> dict | None:
        """Get user info including registration date."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, username, first_name, last_name, created_at FROM users WHERE user_id = ?",
                (user_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "user_id": row[0],
            "username": row[1],
            "first_name": row[2],
            "last_name": row[3],
            "created_at": row[4],
        }

    def get_user_profile_stats(self, user_id: int) -> dict:
        """Get comprehensive user statistics for profile."""
        with self._connect() as conn:
            # Days since registration
            reg_row = conn.execute(
                "SELECT created_at FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            
            # Chapters read count
            chapters_row = conn.execute(
                "SELECT COUNT(*) FROM reading_history WHERE user_id = ?", (user_id,)
            ).fetchone()
            
            # Favorites count
            fav_row = conn.execute(
                "SELECT COUNT(*) FROM favorites WHERE user_id = ?", (user_id,)
            ).fetchone()
            
            # Unique manga read
            manga_row = conn.execute(
                "SELECT COUNT(DISTINCT manga_id) FROM reading_history WHERE user_id = ?", (user_id,)
            ).fetchone()
        
        # Calculate days since registration
        days_registered = 0
        if reg_row and reg_row[0]:
            try:
                reg_date = datetime.fromisoformat(reg_row[0].replace('Z', '+00:00'))
                days_registered = (datetime.now() - reg_date.replace(tzinfo=None)).days
            except (ValueError, AttributeError):
                days_registered = 0
        
        chapters_read = chapters_row[0] if chapters_row else 0
        favorites_count = fav_row[0] if fav_row else 0
        manga_read = manga_row[0] if manga_row else 0
        
        # Determine rank based on chapters read
        rank = self._get_rank(chapters_read)
        
        return {
            "days_registered": days_registered,
            "chapters_read": chapters_read,
            "favorites_count": favorites_count,
            "manga_read": manga_read,
            "rank": rank,
        }

    @staticmethod
    def _get_rank(chapters_read: int) -> str:
        """Determine user rank based on chapters read."""
        if chapters_read >= 1000:
            return "🏆 Легенда манги"
        elif chapters_read >= 500:
            return "👑 Мастер чтения"
        elif chapters_read >= 200:
            return "⭐ Опытный читатель"
        elif chapters_read >= 50:
            return "📖 Активный читатель"
        elif chapters_read >= 10:
            return "📚 Начинающий"
        else:
            return "🌱 Новичок"

    def get_all_users(self, include_blocked: bool = False) -> list[int]:
        """Get all tracked user IDs."""
        with self._connect() as conn:
            if include_blocked:
                rows = conn.execute("SELECT user_id FROM users").fetchall()
            else:
                rows = conn.execute("SELECT user_id FROM users WHERE is_blocked = 0").fetchall()
        return [row[0] for row in rows]

    def get_user_count(self, include_blocked: bool = False) -> int:
        """Get total number of users."""
        with self._connect() as conn:
            if include_blocked:
                row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 0").fetchone()
        return row[0] if row else 0

    def block_user(self, user_id: int) -> None:
        """Mark user as blocked (won't receive broadcasts)."""
        with self._connect() as conn:
            conn.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user_id,))
            conn.commit()

    def get_active_users(self, days: int = 7) -> list[int]:
        """Get users active in the last N days."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id FROM users 
                WHERE is_blocked = 0 
                AND last_active >= datetime('now', ?)
                """,
                (f'-{days} days',)
            ).fetchall()
        return [row[0] for row in rows]

    # ========== Favorites Methods ==========

    def add(self, user_id: int, manga_id: int, title: str, cover: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO favorites (user_id, manga_id, title, cover, added_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
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
                "SELECT manga_id, title, cover FROM favorites WHERE user_id = ? ORDER BY added_at DESC",
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

    def get_favorites_count(self, user_id: int) -> int:
        """Get number of favorites for a user."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM favorites WHERE user_id = ?",
                (user_id,)
            ).fetchone()
        return row[0] if row else 0

    # ========== Reading History Methods ==========

    def mark_chapter_read(
        self, user_id: int, manga_id: int, chapter_id: int, chapter_num: str | None = None
    ) -> None:
        """Mark a chapter as read."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reading_history (user_id, manga_id, chapter_id, chapter_num, read_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (user_id, manga_id, chapter_id, chapter_num),
            )
            conn.commit()

    def get_read_chapters(self, user_id: int, manga_id: int) -> list[int]:
        """Get list of read chapter IDs for a manga."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT chapter_id FROM reading_history WHERE user_id = ? AND manga_id = ?",
                (user_id, manga_id),
            ).fetchall()
        return [row[0] for row in rows]

    def get_last_read_chapter(self, user_id: int, manga_id: int) -> int | None:
        """Get the last read chapter ID for a manga."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT chapter_id FROM reading_history 
                WHERE user_id = ? AND manga_id = ?
                ORDER BY read_at DESC LIMIT 1
                """,
                (user_id, manga_id),
            ).fetchone()
        return row[0] if row else None

    # ========== Stats Methods ==========

    def get_stats(self) -> dict:
        """Get overall bot statistics."""
        with self._connect() as conn:
            total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            active_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE last_active >= datetime('now', '-7 days')"
            ).fetchone()[0]
            total_favorites = conn.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
            total_reads = conn.execute("SELECT COUNT(*) FROM reading_history").fetchone()[0]
            cached_files = conn.execute("SELECT COUNT(*) FROM file_cache").fetchone()[0]
        return {
            "total_users": total_users,
            "active_users_7d": active_users,
            "total_favorites": total_favorites,
            "total_chapter_reads": total_reads,
            "cached_files": cached_files,
        }

    # ========== File Cache Methods ==========

    def get_cached_file(self, manga_id: int, chapter_id: int, format: str) -> str | None:
        """Get cached Telegram file_id if exists."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT file_id FROM file_cache WHERE manga_id = ? AND chapter_id = ? AND format = ?",
                (manga_id, chapter_id, format),
            ).fetchone()
        return row[0] if row else None

    def cache_file(
        self, manga_id: int, chapter_id: int, format: str, file_id: str, file_name: str | None = None
    ) -> None:
        """Cache a Telegram file_id for a chapter."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO file_cache (manga_id, chapter_id, format, file_id, file_name, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (manga_id, chapter_id, format, file_id, file_name),
            )
            conn.commit()

    def clear_file_cache(self, manga_id: int | None = None) -> int:
        """Clear file cache. If manga_id provided, clear only for that manga."""
        with self._connect() as conn:
            if manga_id:
                cursor = conn.execute("DELETE FROM file_cache WHERE manga_id = ?", (manga_id,))
            else:
                cursor = conn.execute("DELETE FROM file_cache")
            conn.commit()
            return cursor.rowcount

    # ========== Album Cache Methods ==========

    def get_cached_album(self, manga_id: int, chapter_id: int) -> list[list[str]] | None:
        """Get cached album file_ids. Returns list of batches, each batch is list of file_ids."""
        import json
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT batch_index, file_ids FROM album_cache WHERE manga_id = ? AND chapter_id = ? ORDER BY batch_index",
                (manga_id, chapter_id),
            ).fetchall()
        if not rows:
            return None
        return [json.loads(row[1]) for row in rows]

    def cache_album_batch(self, manga_id: int, chapter_id: int, batch_index: int, file_ids: list[str]) -> None:
        """Cache a batch of album file_ids."""
        import json
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO album_cache (manga_id, chapter_id, batch_index, file_ids, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (manga_id, chapter_id, batch_index, json.dumps(file_ids)),
            )
            conn.commit()

    def clear_album_cache(self, manga_id: int | None = None) -> int:
        """Clear album cache. If manga_id provided, clear only for that manga."""
        with self._connect() as conn:
            if manga_id:
                cursor = conn.execute("DELETE FROM album_cache WHERE manga_id = ?", (manga_id,))
            else:
                cursor = conn.execute("DELETE FROM album_cache")
            conn.commit()
            return cursor.rowcount

    # ========== User Settings Methods ==========

    def get_download_format(self, user_id: int) -> str:
        """Get user's preferred download format. Default is 'pdf'."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT download_format FROM user_settings WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row[0] if row else "pdf"

    def set_download_format(self, user_id: int, format: str) -> None:
        """Set user's preferred download format ('pdf' or 'zip')."""
        if format not in ("pdf", "zip"):
            raise ValueError("Format must be 'pdf' or 'zip'")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_settings (user_id, download_format, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET 
                    download_format = excluded.download_format,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, format),
            )
            conn.commit()

    # ========== Manga History Methods ==========

    def add_manga_to_history(self, user_id: int, manga_id: int, title: str, cover: str | None = None) -> None:
        """Add manga to user's viewing history."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO manga_history (user_id, manga_id, title, cover, viewed_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, manga_id) DO UPDATE SET 
                    title = excluded.title,
                    cover = excluded.cover,
                    viewed_at = CURRENT_TIMESTAMP
                """,
                (user_id, manga_id, title, cover),
            )
            conn.commit()

    def get_recent_manga(self, user_id: int, limit: int = 10) -> list[dict]:
        """Get user's recently viewed manga."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT manga_id, title, cover, viewed_at 
                FROM manga_history 
                WHERE user_id = ? 
                ORDER BY viewed_at DESC 
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [
            {"manga_id": row[0], "title": row[1], "cover": row[2], "viewed_at": row[3]}
            for row in rows
        ]

    # ========== Chapter Count Tracking (for notifications) ==========

    def get_manga_chapter_count(self, manga_id: int) -> int | None:
        """Get last known chapter count for a manga."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT chapter_count FROM manga_chapter_count WHERE manga_id = ?",
                (manga_id,),
            ).fetchone()
        return row[0] if row else None

    def set_manga_chapter_count(self, manga_id: int, count: int) -> None:
        """Update chapter count for a manga."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO manga_chapter_count (manga_id, chapter_count, last_checked)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(manga_id) DO UPDATE SET 
                    chapter_count = excluded.chapter_count,
                    last_checked = CURRENT_TIMESTAMP
                """,
                (manga_id, count),
            )
            conn.commit()

    def get_all_favorite_manga_ids(self) -> list[tuple[int, int, str]]:
        """Get all unique manga IDs from favorites with user_id and title."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT manga_id, user_id, title FROM favorites"
            ).fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    def get_users_with_favorite(self, manga_id: int) -> list[int]:
        """Get all user IDs who have this manga in favorites."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT user_id FROM favorites WHERE manga_id = ?",
                (manga_id,),
            ).fetchall()
        return [row[0] for row in rows]

    # ========== Notification Settings ==========

    def is_notifications_enabled(self, user_id: int) -> bool:
        """Check if user has notifications enabled."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT notifications_enabled FROM notification_settings WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row[0] == 1 if row else True  # Default enabled

    def set_notifications_enabled(self, user_id: int, enabled: bool) -> None:
        """Enable or disable notifications for user."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO notification_settings (user_id, notifications_enabled)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET notifications_enabled = excluded.notifications_enabled
                """,
                (user_id, 1 if enabled else 0),
            )
            conn.commit()

    # ========== Error Logging ==========

    def log_error(self, error_type: str, error_message: str, context: str | None = None) -> None:
        """Log an error to the database."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO error_log (error_type, error_message, context)
                VALUES (?, ?, ?)
                """,
                (error_type, error_message, context),
            )
            conn.commit()

    def get_recent_errors(self, limit: int = 50) -> list[dict]:
        """Get recent errors from log."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, error_type, error_message, context, created_at 
                FROM error_log 
                ORDER BY created_at DESC 
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "error_type": row[1],
                "error_message": row[2],
                "context": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]

    def clear_old_errors(self, days: int = 30) -> int:
        """Clear errors older than specified days."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM error_log WHERE created_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            conn.commit()
            return cursor.rowcount
