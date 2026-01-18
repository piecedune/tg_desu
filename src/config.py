"""Configuration and constants for the bot."""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# Telegram token
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# Telethon API credentials (get from https://my.telegram.org)
API_ID = int(os.getenv("API_ID", "0")) or None
API_HASH = os.getenv("API_HASH", "")

# Desu API base URL
DESU_BASE_URL = os.getenv("DESU_BASE_URL", "https://x.desu.city")

# Admin Telegram ID
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) or None

# Bot username (for deep links, set automatically on start or via env)
BOT_USERNAME: str | None = os.getenv("BOT_USERNAME")

# Popular manga genres (English names for API, Russian for UI)
GENRES = {
    "Action": "Экшен",
    "Adventure": "Приключения",
    "Comedy": "Комедия",
    "Drama": "Драма",
    "Fantasy": "Фэнтези",
    "Horror": "Ужасы",
    "Mystery": "Мистика",
    "Romance": "Романтика",
    "Sci-Fi": "Научная фантастика",
    "Slice of Life": "Повседневность",
    "Sports": "Спорт",
    "Supernatural": "Сверхъестественное",
    "Thriller": "Триллер",
    "Martial Arts": "Боевые искусства",
    "Psychological": "Психология",
    "School": "Школа",
    "Seinen": "Сэйнэн",
    "Shounen": "Сёнэн",
    "Shoujo": "Сёдзё",
    "Josei": "Дзёсэй",
    "Isekai": "Исекай",
    "Harem": "Гарем",
    "Mecha": "Меха",
    "Historical": "История",
}


def get_token() -> str:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not set")
    return TELEGRAM_TOKEN


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return ADMIN_ID is not None and user_id == ADMIN_ID
