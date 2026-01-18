"""Keyboard builders for the bot."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from config import GENRES


# Main menu keyboard
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📚 Каталог"), KeyboardButton(text="🔍 Поиск")],
        [KeyboardButton(text="🎲 Случайная")]
    ],
    resize_keyboard=True,
)


def build_search_menu() -> InlineKeyboardMarkup:
    """Build search options menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏷 Жанры", callback_data="search:genres")],
            [InlineKeyboardButton(text="🔤 По названию", callback_data="search:keywords")],
            [InlineKeyboardButton(text="🆕 Новинки", callback_data="search:new")],
            [InlineKeyboardButton(text="🔥 Популярное", callback_data="search:popular")],
        ]
    )


def build_catalog_menu() -> InlineKeyboardMarkup:
    """Build catalog menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Новинки", callback_data="search:new")],
            [InlineKeyboardButton(text="🔥 Популярное", callback_data="search:popular")],
        ]
    )


def build_genre_keyboard(page: int = 1, per_page: int = 12, columns: int = 3) -> InlineKeyboardMarkup:
    """Build keyboard with genre buttons."""
    genre_list = list(GENRES.items())
    start = (page - 1) * per_page
    end = start + per_page
    page_genres = genre_list[start:end]
    
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for api_name, display_name in page_genres:
        row.append(InlineKeyboardButton(text=display_name, callback_data=f"genre:{api_name}"))
        if len(row) == columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    
    # Navigation
    navigation: list[InlineKeyboardButton] = []
    if start > 0:
        navigation.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"genres_page:{page - 1}"))
    if end < len(genre_list):
        navigation.append(InlineKeyboardButton(text="Далее ▶", callback_data=f"genres_page:{page + 1}"))
    if navigation:
        rows.append(navigation)
    
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_chapter_keyboard(
    chapters: list[dict], 
    manga_id: int, 
    page: int, 
    per_page: int = 12, 
    columns: int = 4,
    read_chapter_ids: set[int] | None = None
) -> InlineKeyboardMarkup:
    """Build keyboard with chapter buttons. Read chapters marked with ✅."""
    from utils import chapter_title
    
    if read_chapter_ids is None:
        read_chapter_ids = set()
    
    start = (page - 1) * per_page
    end = start + per_page
    page_chapters = chapters[start:end]

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for chapter in page_chapters:
        chapter_id = chapter.get("id")
        label = chapter_title(chapter)
        # Add checkmark if chapter was read
        if chapter_id in read_chapter_ids:
            label = f"✅{label}"
        row.append(InlineKeyboardButton(text=label, callback_data=f"chapter:{manga_id}:{chapter_id}"))
        if len(row) == columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    navigation: list[InlineKeyboardButton] = []
    if start > 0:
        navigation.append(
            InlineKeyboardButton(text="◀ Назад", callback_data=f"chapters:{manga_id}:{page - 1}")
        )
    if end < len(chapters):
        navigation.append(
            InlineKeyboardButton(text="Далее ▶", callback_data=f"chapters:{manga_id}:{page + 1}")
        )
    if navigation:
        rows.append(navigation)
    
    # Add "Go to chapter" button if there are many chapters
    if len(chapters) > per_page:
        rows.append([InlineKeyboardButton(text="🔢 Ввести номер главы", callback_data=f"goto_ch:{manga_id}")])
    
    # Add "Download volume" button
    rows.append([InlineKeyboardButton(text="📚 Скачать том", callback_data=f"volumes:{manga_id}")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_manga_buttons(manga_id: int, is_favorite: bool, bot_username: str | None = None) -> InlineKeyboardMarkup:
    """Build manga detail buttons with share link."""
    from urllib.parse import quote
    
    action = "remove" if is_favorite else "add"
    fav_text = "⭐ Убрать из избранного" if is_favorite else "⭐ В избранное"
    
    buttons = [
        [InlineKeyboardButton(text="📖 Главы", callback_data=f"chapters:{manga_id}:1")],
        [InlineKeyboardButton(text=fav_text, callback_data=f"fav:{action}:{manga_id}")],
    ]
    
    # Add share button - opens Telegram share dialog
    if bot_username:
        manga_link = f"https://t.me/{bot_username}?start=manga_{manga_id}"
        share_url = f"https://t.me/share/url?url={quote(manga_link)}&text={quote('Смотри эту мангу! 📚')}"
        buttons.append([InlineKeyboardButton(text="📤 Поделиться", url=share_url)])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_format_keyboard(manga_id: int, chapter_id: int, default_format: str = "pdf") -> InlineKeyboardMarkup:
    """Build download format choice keyboard with album reading option."""
    pdf_mark = " ⭐" if default_format == "pdf" else ""
    cbz_mark = " ⭐" if default_format == "cbz" else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👁 Читать здесь", callback_data=f"read_album:{manga_id}:{chapter_id}")],
        [
            InlineKeyboardButton(text=f"📕 PDF{pdf_mark}", callback_data=f"dl_pdf:{manga_id}:{chapter_id}"),
            InlineKeyboardButton(text=f"📦 CBZ{cbz_mark}", callback_data=f"dl_zip:{manga_id}:{chapter_id}"),
        ],
        [InlineKeyboardButton(text="◀ Назад", callback_data=f"chapters:{manga_id}:1")]
    ])


def build_volume_list_keyboard(volumes: list[str | int], manga_id: int) -> InlineKeyboardMarkup:
    """Build keyboard with volume buttons for download."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    
    for vol in volumes:
        vol_str = str(vol) if vol else "?"
        row.append(InlineKeyboardButton(
            text=f"Том {vol_str}", 
            callback_data=f"vol_format:{manga_id}:{vol_str}"
        ))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    
    rows.append([InlineKeyboardButton(text="◀ Назад", callback_data=f"chapters:{manga_id}:1")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_volume_format_keyboard(manga_id: int, volume: str) -> InlineKeyboardMarkup:
    """Build format choice keyboard for volume download."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📕 PDF", callback_data=f"dl_vol_pdf:{manga_id}:{volume}"),
            InlineKeyboardButton(text="📦 CBZ", callback_data=f"dl_vol_cbz:{manga_id}:{volume}"),
        ],
        [InlineKeyboardButton(text="◀ Назад", callback_data=f"volumes:{manga_id}")]
    ])


def build_search_results(
    results: list, 
    page: int = 1, 
    per_page: int = 10,
    search_type: str = "search",
    search_query: str = ""
) -> InlineKeyboardMarkup:
    """Build search results keyboard with pagination.
    
    search_type: 'new', 'popular', 'keywords', 'genre'
    search_query: keyword text or genre api name
    """
    start = (page - 1) * per_page
    end = start + per_page
    page_results = results[start:end]
    
    keyboard = [
        [InlineKeyboardButton(text=result.title, callback_data=f"manga:{result.id}")]
        for result in page_results
    ]
    
    # Navigation buttons
    navigation: list[InlineKeyboardButton] = []
    # Encode search info: type:query:page
    if start > 0:
        navigation.append(InlineKeyboardButton(
            text="◀ Назад", 
            callback_data=f"results:{search_type}:{search_query}:{page - 1}"
        ))
    if end < len(results):
        navigation.append(InlineKeyboardButton(
            text="Далее ▶", 
            callback_data=f"results:{search_type}:{search_query}:{page + 1}"
        ))
    if navigation:
        keyboard.append(navigation)
    
    # Show page info if multiple pages
    total_pages = (len(results) + per_page - 1) // per_page
    if total_pages > 1:
        keyboard.append([InlineKeyboardButton(
            text=f"📄 {page}/{total_pages} ({len(results)} шт.)", 
            callback_data="noop"
        )])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ========== Profile Keyboards ==========

def build_profile_menu() -> InlineKeyboardMarkup:
    """Build main profile menu keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Избранное", callback_data="profile:favorites")],
            [InlineKeyboardButton(text="📖 История просмотров", callback_data="profile:history")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="profile:settings")],
        ]
    )


def build_favorites_keyboard(favorites: list[dict], page: int = 1, per_page: int = 10) -> InlineKeyboardMarkup:
    """Build favorites list keyboard with pagination."""
    start = (page - 1) * per_page
    end = start + per_page
    page_favorites = favorites[start:end]
    
    rows: list[list[InlineKeyboardButton]] = []
    for fav in page_favorites:
        title = fav["title"][:40] + "..." if len(fav["title"]) > 40 else fav["title"]
        rows.append([
            InlineKeyboardButton(text=f"📚 {title}", callback_data=f"manga:{fav['manga_id']}")
        ])
    
    # Navigation
    navigation: list[InlineKeyboardButton] = []
    if start > 0:
        navigation.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"fav_page:{page - 1}"))
    if end < len(favorites):
        navigation.append(InlineKeyboardButton(text="Далее ▶", callback_data=f"fav_page:{page + 1}"))
    if navigation:
        rows.append(navigation)
    
    rows.append([InlineKeyboardButton(text="🔙 В профиль", callback_data="profile:main")])
    
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_history_keyboard(history: list[dict], page: int = 1, per_page: int = 10) -> InlineKeyboardMarkup:
    """Build viewing history keyboard with pagination."""
    start = (page - 1) * per_page
    end = start + per_page
    page_history = history[start:end]
    
    rows: list[list[InlineKeyboardButton]] = []
    for item in page_history:
        title = item["title"][:40] + "..." if len(item["title"]) > 40 else item["title"]
        rows.append([
            InlineKeyboardButton(text=f"📖 {title}", callback_data=f"manga:{item['manga_id']}")
        ])
    
    # Navigation
    navigation: list[InlineKeyboardButton] = []
    if start > 0:
        navigation.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"history_page:{page - 1}"))
    if end < len(history):
        navigation.append(InlineKeyboardButton(text="Далее ▶", callback_data=f"history_page:{page + 1}"))
    if navigation:
        rows.append(navigation)
    
    rows.append([InlineKeyboardButton(text="🔙 В профиль", callback_data="profile:main")])
    
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_settings_keyboard(current_format: str) -> InlineKeyboardMarkup:
    """Build settings keyboard."""
    pdf_check = "✅" if current_format == "pdf" else ""
    zip_check = "✅" if current_format == "zip" else ""
    
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"📕 PDF {pdf_check}", callback_data="set_format:pdf")],
            [InlineKeyboardButton(text=f"🗂 ZIP {zip_check}", callback_data="set_format:zip")],
            [InlineKeyboardButton(text="🔙 В профиль", callback_data="profile:main")],
        ]
    )
