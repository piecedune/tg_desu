# Copilot Instructions for Desu Manga Telegram Bot

## Architecture Overview

This is an **aiogram 3.x** Telegram bot that interfaces with the Desu manga API. Modular architecture:

```
src/
├── bot.py              # Entry point - bot initialization
├── config.py           # Configuration, constants, genres
├── keyboards.py        # All keyboard builders
├── utils.py            # Download, PDF/ZIP creation utilities
├── states.py           # FSM state definitions
├── dependencies.py     # Dependency injection (client, store)
├── desu_client.py      # Sync HTTP client for Desu API
├── favorites.py        # SQLite storage (users, favorites, cache)
└── handlers/
    ├── __init__.py     # Router setup
    ├── base.py         # /start, Profile, Catalog, Search
    ├── search.py       # Genre/keyword search handlers
    ├── manga.py        # Manga details, chapters, downloads
    └── admin.py        # Broadcast, stats (admin only)
```

## Key Patterns

### Async/Sync Bridge
The `DesuClient` uses synchronous `requests`. Bot handlers wrap calls with `run_sync()`:
```python
from utils import run_sync
results = await run_sync(client.search_manga, keywords=message.text)
```

### Dependency Injection
Initialize in `bot.py`, access anywhere:
```python
from dependencies import get_client, get_favorites
client = get_client()   # Returns DesuClient
store = get_favorites() # Returns FavoritesStore
```

### Callback Data Format
Inline button callbacks use colon-separated format: `action:param1:param2`
- `manga:{id}` - Show manga details
- `chapters:{manga_id}:{page}` - Paginated chapter list
- `chapter:{manga_id}:{chapter_id}` - Show format choice
- `dl_pdf:{manga_id}:{chapter_id}` - Download as PDF
- `dl_zip:{manga_id}:{chapter_id}` - Download as ZIP
- `fav:add|remove:{manga_id}` - Toggle favorites
- `search:new|popular|keywords|genres` - Search actions
- `genre:{api_name}` - Search by genre
- `genres_page:{page}` - Genre pagination
- `goto_ch:{manga_id}` - Enter chapter number manually
- `broadcast:confirm|cancel` - Admin broadcast

### FSM States (states.py)
```python
class SearchStates(StatesGroup):
    keywords = State()           # Awaiting keyword input

class ChapterStates(StatesGroup):
    waiting_chapter_number = State()  # Awaiting chapter number

class BroadcastStates(StatesGroup):
    waiting_content = State()    # Admin: awaiting broadcast content
    confirm = State()            # Admin: confirmation step
```

## Data Models

### desu_client.py
- **`MangaSummary`** - List/search results (id, title, cover, genres)  
- **`MangaDetail`** - Full manga info (adds year, description, chapters_count, rating)

API responses use `russian` field for localized titles with `title` as fallback.

### favorites.py - Database Schema
```sql
-- User tracking with activity
users (user_id, username, first_name, last_name, created_at, last_active, is_blocked)

-- Favorites with timestamp
favorites (user_id, manga_id, title, cover, added_at)

-- Reading history
reading_history (user_id, manga_id, chapter_id, chapter_num, read_at)

-- File cache (Telegram file_id for instant re-sending)
file_cache (manga_id, chapter_id, format, file_id, file_name, created_at)
```

### Key Store Methods
```python
# Users
store.add_user(user_id, username, first_name, last_name)
store.get_all_users(include_blocked=False) -> list[int]
store.get_user_count() -> int
store.get_active_users(days=7) -> list[int]
store.block_user(user_id)

# Favorites
store.add(user_id, manga_id, title, cover)
store.remove(user_id, manga_id)
store.list(user_id) -> list[tuple]
store.has(user_id, manga_id) -> bool

# Reading history
store.mark_chapter_read(user_id, manga_id, chapter_id, chapter_num)
store.get_read_chapters(user_id, manga_id) -> list[int]
store.get_last_read_chapter(user_id, manga_id) -> int | None

# File cache (avoid re-uploading)
store.get_cached_file(manga_id, chapter_id, format) -> str | None
store.cache_file(manga_id, chapter_id, format, file_id, file_name)
store.clear_file_cache(manga_id=None) -> int

# Stats
store.get_stats() -> dict  # total_users, active_users_7d, total_favorites, etc.
```

## Configuration (config.py)

### Environment Variables
- `TELEGRAM_TOKEN` (required) - Bot token from @BotFather
- `DESU_BASE_URL` (optional) - Defaults to `https://desu.uno`
- `ADMIN_ID` (optional) - Telegram user ID for admin commands

### Genre Mapping
```python
GENRES = {
    "Action": "Экшен",      # API name -> Display name (Russian)
    "Romance": "Романтика",
    # ... 24 genres total
}
```
Use English names for API calls, Russian names for display.

## Keyboards (keyboards.py)

```python
MAIN_MENU                    # ReplyKeyboard: Profile, Catalog, Search
build_search_menu()          # Genres, Keywords, New, Popular
build_catalog_menu()         # New Releases, Popular
build_genre_keyboard(page)   # Paginated genre selection
build_chapter_keyboard(...)  # Paginated chapters with "Enter number" button
build_manga_buttons(...)     # Chapters + Add/Remove Favorite
build_format_keyboard(...)   # PDF / ZIP choice
build_search_results(...)    # Manga list from search
```

## Utils (utils.py)

```python
# Async wrapper for sync functions
await run_sync(func, *args, **kwargs)

# Chapter title formatting
chapter_title(chapter_dict) -> str  # "V1 Ch.10" or "Chapter"

# Manga detail formatting (truncates for Telegram limits)
format_manga_detail(detail, max_length=1000) -> str

# Image download with proper headers
download_image(url) -> Image | None  # Includes Referer header

# File creation
create_pdf_from_images(images, output_path)
create_zip_from_images(images, output_path)
await download_chapter_as_pdf(pages, chapter_name) -> str | None
await download_chapter_as_zip(pages, chapter_name) -> str | None
```

## Admin Features

### Commands (only for ADMIN_ID user)
- `/broadcast` - Send message/photo to all users
- `/stats` - Show bot statistics
- `/cancel` - Cancel current operation

### Broadcast Flow
1. Admin sends `/broadcast`
2. Admin sends text or photo with caption
3. Confirmation buttons appear
4. On confirm: sends to all non-blocked users with 50ms delay

## Development

### Run the bot
```bash
cd src
python bot.py
```

### Adding New Handlers
1. Create handler in appropriate file under `handlers/`
2. Use `@router.message()` or `@router.callback_query()` decorators
3. For callback queries, always call `await callback.answer()` first
4. Check `callback.message` existence before editing
5. Import dependencies: `from dependencies import get_client, get_favorites`

### File Caching Strategy
When sending documents:
1. Check `store.get_cached_file(manga_id, chapter_id, format)`
2. If cached: send by `file_id` (instant)
3. If not: download, create file, send, then `store.cache_file(...)` the returned `file_id`

### Error Handling Pattern
```python
try:
    await callback.message.edit_text("...")
except Exception:
    await callback.message.answer("...")  # Fallback for photos/etc
```

## Files

- `favorites.db` - SQLite database (created in working directory)
- `.env` - Environment configuration (not committed)

## API Notes

### Desu API (desu.uno)
- Base endpoint: `/manga/api`
- Search params: `search`, `genres` (English), `order` (popular/updated), `limit`, `page`
- Response wrapped in `{"response": [...]}` 
- Genres in response are comma-separated strings, not arrays
- Images require `Referer: https://desu.uno/` header
