# Copilot Instructions for Desu Manga Telegram Bot

## Architecture Overview

**aiogram 3.x** Telegram bot для работы с Desu manga API. Модульная архитектура:

```
src/
├── bot.py              # Точка входа, инициализация бота
├── config.py           # Конфигурация, константы, жанры
├── keyboards.py        # Все билдеры клавиатур
├── utils.py            # Скачивание, создание PDF/ZIP
├── states.py           # FSM состояния
├── dependencies.py     # Инъекция зависимостей (client, store)
├── desu_client.py      # Синхронный HTTP клиент Desu API
├── favorites.py        # SQLite хранилище
├── middlewares.py      # Антиспам middleware
└── handlers/
    ├── __init__.py     # Настройка роутеров
    ├── base.py         # /start, Profile, Catalog, Search, Random
    ├── search.py       # Поиск по жанрам/названию с пагинацией
    ├── manga.py        # Детали манги, главы, скачивание, альбомы
    └── admin.py        # Рассылка, статистика, бэкап (только админ)
```

## Key Patterns

### Async/Sync Bridge
`DesuClient` использует синхронный `requests`. Хендлеры оборачивают вызовы в `run_sync()`:
```python
from utils import run_sync
results = await run_sync(client.search_manga, keywords=message.text)
```

### Dependency Injection
Инициализация в `bot.py`, доступ откуда угодно:
```python
from dependencies import get_client, get_favorites
client = get_client()   # DesuClient
store = get_favorites() # FavoritesStore
```

### Callback Data Format
Inline кнопки используют формат через двоеточие: `action:param1:param2`

**Основные:**
- `manga:{id}` — детали манги
- `chapters:{manga_id}:{page}` — список глав с пагинацией
- `chapter:{manga_id}:{chapter_id}` — выбор формата
- `read_album:{manga_id}:{chapter_id}` — читать как альбом
- `dl_pdf:{manga_id}:{chapter_id}` — скачать PDF
- `dl_zip:{manga_id}:{chapter_id}` — скачать CBZ
- `fav:add|remove:{manga_id}` — добавить/убрать из избранного

**Тома:**
- `volumes:{manga_id}` — список томов для скачивания
- `vol_format:{manga_id}:{vol}` — выбор формата тома
- `dl_vol_pdf:{manga_id}:{vol}` — скачать том как PDF
- `dl_vol_cbz:{manga_id}:{vol}` — скачать том как CBZ

**Поиск:**
- `search:new|popular|keywords|genres` — типы поиска
- `genre:{api_name}` — поиск по жанру
- `genres_page:{page}` — пагинация жанров
- `results:{type}:{query}:{page}` — пагинация результатов поиска

**Навигация:**
- `goto_ch:{manga_id}` — ввести номер главы
- `profile:favorites|history|settings` — разделы профиля

**Админ:**
- `broadcast:confirm|cancel` — подтверждение рассылки

### FSM States (states.py)
```python
class SearchStates(StatesGroup):
    keywords = State()                # Ввод ключевых слов

class ChapterStates(StatesGroup):
    waiting_chapter_number = State()  # Ввод номера главы

class BroadcastStates(StatesGroup):
    waiting_content = State()         # Контент рассылки
    confirm = State()                 # Подтверждение
```

## Data Models

### desu_client.py
- **`MangaSummary`** — результаты поиска (id, title, cover, genres)
- **`MangaDetail`** — полная инфо (+ year, description, chapters_count, rating)

API возвращает `russian` для локализованных названий, `title` как fallback.

### favorites.py — Database Schema
```sql
-- Пользователи
users (user_id, username, first_name, last_name, created_at, last_active, is_blocked)

-- Избранное
favorites (user_id, manga_id, title, cover, added_at)

-- История чтения
reading_history (user_id, manga_id, chapter_id, chapter_num, read_at)

-- Кэш файлов (Telegram file_id)
file_cache (manga_id, chapter_id, format, file_id, file_name, created_at)

-- Кэш альбомов (file_id страниц)
album_cache (manga_id, chapter_id, batch_index, file_ids, created_at)

-- Настройки пользователя
user_settings (user_id, download_format, updated_at)

-- История просмотров манги
manga_history (user_id, manga_id, title, cover, viewed_at)

-- Счетчик глав (для уведомлений)
manga_chapter_count (manga_id, chapter_count, last_checked)

-- Настройки уведомлений
notification_settings (user_id, notifications_enabled)

-- Лог ошибок
error_log (id, error_type, error_message, context, created_at)
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
store.get_all_favorited_manga_ids() -> set[int]

# Reading history
store.mark_chapter_read(user_id, manga_id, chapter_id, chapter_num)
store.get_read_chapters(user_id, manga_id) -> set[int]
store.get_last_read_chapter(user_id, manga_id) -> int | None

# File cache
store.get_cached_file(manga_id, chapter_id, format) -> str | None
store.cache_file(manga_id, chapter_id, format, file_id, file_name)
store.clear_file_cache(manga_id=None) -> int

# Album cache
store.get_cached_album(manga_id, chapter_id) -> list[list[str]] | None
store.cache_album_batch(manga_id, chapter_id, batch_index, file_ids)
store.clear_album_cache(manga_id=None) -> int

# Notifications
store.get_users_with_favorite(manga_id) -> list[int]
store.get_manga_chapter_count(manga_id) -> int | None
store.set_manga_chapter_count(manga_id, count)
store.get_notification_enabled(user_id) -> bool
store.set_notification_enabled(user_id, enabled)

# Error logging
store.log_error(error_type, error_message, context=None)
store.get_recent_errors(limit=50) -> list[tuple]

# Stats
store.get_stats() -> dict
```

## Configuration (config.py)

### Environment Variables
- `TELEGRAM_TOKEN` (required) — токен от @BotFather
- `DESU_BASE_URL` (optional) — по умолчанию `https://desu.uno`
- `ADMIN_ID` (optional) — Telegram ID админа

### Genre Mapping
```python
GENRES = {
    "Action": "Экшен",       # API name -> Display name (Russian)
    "Romance": "Романтика",
    # ... 24+ жанров
}
```
Для API используй английские названия, для UI — русские.

## Keyboards (keyboards.py)

```python
MAIN_MENU                              # ReplyKeyboard: Профиль, Каталог, Поиск, Случайная
build_search_menu()                    # Жанры, По названию, Новинки, Популярное
build_catalog_menu()                   # Новинки, Популярное
build_genre_keyboard(page)             # Пагинация жанров
build_chapter_keyboard(chapters, ..., read_chapter_ids)  # Главы с ✅ для прочитанных
build_manga_buttons(manga_id, is_favorite, bot_username)  # Главы + Избранное + Поделиться
build_format_keyboard(manga_id, chapter_id)  # Читать здесь / PDF / CBZ
build_volume_list_keyboard(volumes, manga_id)  # Список томов для скачивания
build_volume_format_keyboard(manga_id, volume)  # PDF / CBZ для тома
build_search_results(results, page, search_type, search_query)  # С пагинацией
build_profile_menu()                   # Избранное, История, Настройки
build_settings_keyboard(format, notifications)  # Настройки пользователя
```

## Utils (utils.py)

```python
# Async wrapper
await run_sync(func, *args, **kwargs)

# Форматирование
chapter_title(chapter_dict) -> str      # "Том 1 Гл.10" или "Глава"
format_manga_detail(detail, max=1000) -> str

# Скачивание (с Referer header)
download_image(url) -> Image | None

# Создание файлов (главы)
create_pdf_from_images(images, output_path)
create_cbz_from_images(images, output_path)
await download_chapter_as_pdf(pages, chapter_name) -> str | None
await download_chapter_as_cbz(pages, chapter_name) -> str | None

# Создание файлов (тома)
await download_volume_as_pdf(pages, volume_name) -> str | None
await download_volume_as_cbz(pages_with_info, volume_name) -> str | None
create_cbz_with_chapters(pages_with_info, output_path)  # CBZ с папками по главам
```

## Middlewares (middlewares.py)

### ThrottlingMiddleware
Антиспам с многоуровневой защитой:
- Rate limiting (интервал между запросами)
- Лимит запросов в минуту (30)
- Система предупреждений (3 до бана)
- Временный бан (60 сек)

```python
ThrottlingMiddleware(
    rate_limit=0.5,              # Мин. интервал сообщений
    callback_limit=0.3,          # Мин. интервал кнопок
    max_requests_per_minute=30,  # Макс. запросов в минуту
    warn_threshold=3,            # Предупреждений до бана
    ban_duration=60,             # Длительность бана (сек)
)
```

## Admin Features

### Commands (только для ADMIN_ID)
- `/broadcast` — рассылка всем пользователям (текст или фото)
- `/stats` — статистика бота
- `/backup` — скачать favorites.db
- `/cancel` — отменить текущую операцию

### Broadcast Flow
1. Админ отправляет `/broadcast`
2. Админ отправляет текст или фото с подписью
3. Появляются кнопки подтверждения
4. При подтверждении: отправка всем с задержкой 50мс

## Development

### Запуск
```bash
cd oes/src
python bot.py
```

### Добавление хендлеров
1. Создай хендлер в `handlers/`
2. Используй `@router.message()` или `@router.callback_query()`
3. Для callback — всегда `await callback.answer()` первым
4. Проверяй `callback.message` перед редактированием
5. Импорты: `from dependencies import get_client, get_favorites`

### File Caching Strategy
```python
# 1. Проверь кэш
cached = store.get_cached_file(manga_id, chapter_id, "pdf")
if cached:
    await message.answer_document(cached)  # Мгновенно!
    return

# 2. Скачай и отправь
sent = await message.answer_document(FSInputFile(path))

# 3. Сохрани file_id
store.cache_file(manga_id, chapter_id, "pdf", sent.document.file_id)
```

### Album Caching
```python
# Первый раз: скачай изображения, отправь, сохрани file_ids
sent_messages = await message.answer_media_group(media_group)
file_ids = [msg.photo[-1].file_id for msg in sent_messages]
store.cache_album_batch(manga_id, chapter_id, batch_index, file_ids)

# Повторно: отправь по file_id
cached = store.get_cached_album(manga_id, chapter_id)
for batch_file_ids in cached:
    media = [InputMediaPhoto(media=fid) for fid in batch_file_ids]
    await message.answer_media_group(media)
```

### Error Handling
```python
try:
    await callback.message.edit_text("...")
except Exception:
    await callback.message.answer("...")  # Fallback для фото и т.д.
```

## Files

- `favorites.db` — SQLite база (создается в рабочей директории)
- `.env` — конфигурация (не коммитить!)
- `menu/` — изображения для меню (опционально)

## API Notes

### Desu API (desu.uno)
- Endpoint: `/manga/api`
- Params: `search`, `genres` (English), `order` (popular/updated), `limit`, `page`
- Response: `{"response": [...]}`
- Жанры в ответе — строки через запятую
- Изображения требуют `Referer: https://desu.uno/`
- Максимальный manga_id для random: ~6965
- Главы содержат поле `vol` для номера тома
