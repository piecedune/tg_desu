from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

import requests
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv

from desu_client import DesuClient, MangaDetail
from favorites import FavoritesStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLIENT: DesuClient | None = None
FAVORITES: FavoritesStore | None = None

router = Router()

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Profile"), KeyboardButton(text="Catalog"), KeyboardButton(text="Search")]],
    resize_keyboard=True,
)


class SearchStates(StatesGroup):
    keywords = State()


class ChapterStates(StatesGroup):
    waiting_chapter_number = State()


class BroadcastStates(StatesGroup):
    waiting_content = State()
    confirm = State()


# Store for tracking users (in-memory, resets on restart)
USERS: set[int] = set()


async def _run_sync(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


def _get_client() -> DesuClient:
    if CLIENT is None:
        raise RuntimeError("Desu client is not initialized")
    return CLIENT


def _get_favorites() -> FavoritesStore:
    if FAVORITES is None:
        raise RuntimeError("Favorites store is not initialized")
    return FAVORITES


def _build_search_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Genres", callback_data="search:genres")],
            [InlineKeyboardButton(text="Keywords", callback_data="search:keywords")],
            [InlineKeyboardButton(text="New Releases", callback_data="search:new")],
            [InlineKeyboardButton(text="Popular", callback_data="search:popular")],
        ]
    )


def _build_catalog_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="New Releases", callback_data="search:new")],
            [InlineKeyboardButton(text="Popular", callback_data="search:popular")],
        ]
    )


# Popular manga genres (English names for API, display names for UI)
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


def _build_genre_keyboard(page: int = 1, per_page: int = 12, columns: int = 3) -> InlineKeyboardMarkup:
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
        navigation.append(InlineKeyboardButton(text="◀ Prev", callback_data=f"genres_page:{page - 1}"))
    if end < len(genre_list):
        navigation.append(InlineKeyboardButton(text="Next ▶", callback_data=f"genres_page:{page + 1}"))
    if navigation:
        rows.append(navigation)
    
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _chapter_title(chapter: dict) -> str:
    # API returns "ch" for chapter number and "vol" for volume
    number = chapter.get("ch") or chapter.get("chapter") or chapter.get("number")
    vol = chapter.get("vol")
    title = chapter.get("title")
    
    if number:
        label = f"Ch.{number}"
        if vol:
            label = f"V{vol} {label}"
        return label
    return title or "Chapter"


def _build_chapter_keyboard(
    chapters: list[dict], manga_id: int, page: int, per_page: int = 12, columns: int = 4
) -> InlineKeyboardMarkup:
    start = (page - 1) * per_page
    end = start + per_page
    page_chapters = chapters[start:end]

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for chapter in page_chapters:
        chapter_id = chapter.get("id")
        label = _chapter_title(chapter)
        row.append(InlineKeyboardButton(text=label, callback_data=f"chapter:{manga_id}:{chapter_id}"))
        if len(row) == columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    navigation: list[InlineKeyboardButton] = []
    if start > 0:
        navigation.append(
            InlineKeyboardButton(text="◀ Prev", callback_data=f"chapters:{manga_id}:{page - 1}")
        )
    if end < len(chapters):
        navigation.append(
            InlineKeyboardButton(text="Next ▶", callback_data=f"chapters:{manga_id}:{page + 1}")
        )
    if navigation:
        rows.append(navigation)
    
    # Add "Go to chapter" button if there are many chapters
    if len(chapters) > per_page:
        rows.append([InlineKeyboardButton(text="🔢 Enter chapter number", callback_data=f"goto_ch:{manga_id}")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart())
async def start(message: Message) -> None:
    # Track user in database with full info
    store = _get_favorites()
    user = message.from_user
    store.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    await message.answer("Welcome to the Desu manga bot!", reply_markup=MAIN_MENU)


@router.message(Command("search"))
async def cmd_search(message: Message) -> None:
    """Handle /search command."""
    await message.answer("Choose how to search:", reply_markup=_build_search_menu())


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    """Admin command to broadcast message to all users."""
    if not _is_admin(message.from_user.id):
        await message.answer("❌ You don't have permission to use this command.")
        return
    
    store = _get_favorites()
    user_count = store.get_user_count()
    
    await state.set_state(BroadcastStates.waiting_content)
    await message.answer(
        f"📢 Broadcast Mode\\n\\n"
        f"Total users: {user_count}\\n\\n"
        f"Send me the content to broadcast:\\n"
        f"- Text message\\n"
        f"- Photo with caption\\n\\n"
        f"Use /cancel to cancel.",
        parse_mode=None
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Cancel current operation."""
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await message.answer("Operation cancelled.", reply_markup=MAIN_MENU)
    else:
        await message.answer("Nothing to cancel.")


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Admin command to show bot statistics."""
    if not _is_admin(message.from_user.id):
        await message.answer("❌ You don't have permission to use this command.")
        return
    
    store = _get_favorites()
    stats = store.get_stats()
    
    await message.answer(
        f"📊 Bot Statistics\n\n"
        f"👥 Total users: {stats['total_users']}\n"
        f"🟢 Active (7 days): {stats['active_users_7d']}\n"
        f"⭐ Total favorites: {stats['total_favorites']}\n"
        f"📖 Chapters read: {stats['total_chapter_reads']}\n"
        f"📦 Cached files: {stats['cached_files']}",
        parse_mode=None
    )


@router.message(BroadcastStates.waiting_content)
async def handle_broadcast_content(message: Message, state: FSMContext) -> None:
    """Handle broadcast content from admin."""
    if not _is_admin(message.from_user.id):
        await state.clear()
        return
    
    # Store the message content
    if message.photo:
        # Photo with optional caption
        await state.update_data(
            content_type="photo",
            photo_id=message.photo[-1].file_id,  # Highest quality
            caption=message.caption or ""
        )
    elif message.text:
        await state.update_data(
            content_type="text",
            text=message.text
        )
    else:
        await message.answer("❌ Please send text or photo with caption.")
        return
    
    await state.set_state(BroadcastStates.confirm)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Confirm & Send", callback_data="broadcast:confirm"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="broadcast:cancel"),
        ]
    ])
    
    store = _get_favorites()
    user_count = store.get_user_count()
    
    await message.answer(
        f"📢 Ready to broadcast to {user_count} users.\\n\\nConfirm?",
        reply_markup=keyboard,
        parse_mode=None
    )


@router.callback_query(F.data == "broadcast:confirm")
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm and send broadcast."""
    await callback.answer()
    
    if not _is_admin(callback.from_user.id):
        await state.clear()
        return
    
    if not callback.message:
        return
    
    data = await state.get_data()
    await state.clear()
    
    content_type = data.get("content_type")
    if not content_type:
        await callback.message.edit_text("❌ No content to broadcast.")
        return
    
    store = _get_favorites()
    users = store.get_all_users()
    
    await callback.message.edit_text(f"📤 Broadcasting to {len(users)} users...")
    
    success = 0
    failed = 0
    
    for user_id in users:
        try:
            if content_type == "photo":
                await callback.bot.send_photo(
                    user_id,
                    photo=data["photo_id"],
                    caption=data.get("caption", "")
                )
            else:
                await callback.bot.send_message(user_id, data["text"])
            success += 1
        except Exception as e:
            logger.error(f"Failed to send to {user_id}: {e}")
            failed += 1
        
        # Small delay to avoid flood limits
        await asyncio.sleep(0.05)
    
    await callback.message.edit_text(
        f"✅ Broadcast complete!\\n\\n"
        f"Sent: {success}\\n"
        f"Failed: {failed}",
        parse_mode=None
    )


@router.callback_query(F.data == "broadcast:cancel")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel broadcast."""
    await callback.answer("Broadcast cancelled.")
    await state.clear()
    if callback.message:
        await callback.message.edit_text("❌ Broadcast cancelled.")


@router.message(Command("new"))
async def cmd_new(message: Message) -> None:
    """Handle /new command - show new releases."""
    loading_msg = await message.answer("⏳ Loading new releases...")
    client = _get_client()
    results = await _run_sync(client.search_manga, is_new=True)
    await _edit_search_results(loading_msg, results)


@router.message(Command("popular"))
async def cmd_popular(message: Message) -> None:
    """Handle /popular command - show popular manga."""
    loading_msg = await message.answer("⏳ Loading popular manga...")
    client = _get_client()
    results = await _run_sync(client.search_manga, popularity=True)
    await _edit_search_results(loading_msg, results)


@router.message(F.text == "Profile")
async def show_profile(message: Message) -> None:
    store = _get_favorites()
    user_id = message.from_user.id
    favorites = list(store.list(user_id))

    if not favorites:
        await message.answer("You have no favorites yet.")
        return

    keyboard = [
        [InlineKeyboardButton(text=title, callback_data=f"manga:{manga_id}")]
        for manga_id, title, _cover in favorites
    ]
    await message.answer("Your favorites:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.message(F.text == "Catalog")
async def show_catalog(message: Message) -> None:
    await message.answer("Browse the catalog:", reply_markup=_build_catalog_menu())


@router.message(F.text == "Search")
async def show_search(message: Message) -> None:
    await message.answer("Choose how to search:", reply_markup=_build_search_menu())


@router.callback_query(F.data == "search:keywords")
async def prompt_keywords(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SearchStates.keywords)
    if callback.message:
        try:
            await callback.message.edit_text("Send keywords to search (e.g. 'dungeon hero').")
        except Exception:
            await callback.message.answer("Send keywords to search (e.g. 'dungeon hero').")


@router.callback_query(F.data == "search:genres")
async def prompt_genres(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message:
        try:
            await callback.message.edit_text(
                "Select a genre:",
                reply_markup=_build_genre_keyboard(page=1)
            )
        except Exception:
            await callback.message.answer(
                "Select a genre:",
                reply_markup=_build_genre_keyboard(page=1)
            )


@router.callback_query(F.data.startswith("genres_page:"))
async def show_genres_page(callback: CallbackQuery) -> None:
    """Handle genre pagination."""
    await callback.answer()
    if not callback.message:
        return
    page = int(callback.data.split(":")[1])
    try:
        await callback.message.edit_text(
            "Select a genre:",
            reply_markup=_build_genre_keyboard(page=page)
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("genre:"))
async def search_by_genre(callback: CallbackQuery) -> None:
    """Search manga by selected genre."""
    await callback.answer()
    if not callback.message:
        return
    api_genre = callback.data.split(":", 1)[1]
    display_name = GENRES.get(api_genre, api_genre)
    
    try:
        await callback.message.edit_text(f"⏳ Searching for {display_name}...")
    except Exception:
        pass
    
    client = _get_client()
    results = await _run_sync(client.search_manga, genres=[api_genre])
    await _edit_search_results(callback.message, results)


@router.callback_query(F.data.in_({"search:new", "search:popular"}))
async def run_quick_search(callback: CallbackQuery) -> None:
    await callback.answer()
    client = _get_client()
    popularity = callback.data == "search:popular"
    is_new = callback.data == "search:new"
    
    # Show loading state
    if callback.message:
        try:
            await callback.message.edit_text("⏳ Loading...")
        except Exception:
            pass
    
    results = await _run_sync(client.search_manga, popularity=popularity, is_new=is_new)
    if callback.message:
        await _edit_search_results(callback.message, results)


@router.message(SearchStates.keywords)
async def search_keywords(message: Message, state: FSMContext) -> None:
    await state.clear()
    client = _get_client()
    results = await _run_sync(client.search_manga, keywords=message.text)
    await _send_search_results(message, results)


async def _send_search_results(target: Message, results: list) -> None:
    """Send search results as a new message (for message handlers)."""
    if not results:
        await target.answer("No results found.")
        return
    keyboard = [
        [InlineKeyboardButton(text=result.title, callback_data=f"manga:{result.id}")]
        for result in results[:10]
    ]
    await target.answer("Select a manga:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


async def _edit_search_results(target: Message, results: list) -> None:
    """Edit existing message with search results (for callback handlers)."""
    if not results:
        try:
            await target.edit_text("No results found.")
        except Exception:
            await target.answer("No results found.")
        return
    keyboard = [
        [InlineKeyboardButton(text=result.title, callback_data=f"manga:{result.id}")]
        for result in results[:10]
    ]
    try:
        await target.edit_text("Select a manga:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    except Exception:
        await target.answer("Select a manga:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data.startswith("manga:"))
async def show_manga(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    manga_id = int(callback.data.split(":")[1])
    client = _get_client()
    store = _get_favorites()
    
    # Show loading
    try:
        await callback.message.edit_text("⏳ Loading manga details...")
    except Exception:
        pass

    detail = await _run_sync(client.get_manga_detail, manga_id)
    is_favorite = store.has(callback.from_user.id, manga_id)

    description = _format_manga_detail(detail)
    buttons = [
        [InlineKeyboardButton(text="Chapters", callback_data=f"chapters:{manga_id}:1")],
        [
            InlineKeyboardButton(
                text="Remove Favorite" if is_favorite else "Add Favorite",
                callback_data=f"fav:{'remove' if is_favorite else 'add'}:{manga_id}",
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Delete the loading message and send photo, or edit if no cover
    if detail.cover:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer_photo(detail.cover, caption=description, reply_markup=reply_markup)
    else:
        try:
            await callback.message.edit_text(description, reply_markup=reply_markup)
        except Exception:
            await callback.message.answer(description, reply_markup=reply_markup)


def _format_manga_detail(detail: MangaDetail, max_length: int = 1000) -> str:
    genres = ", ".join(detail.genres) if detail.genres else "Unknown"
    year = detail.year or "Unknown"
    rating = detail.rating or "N/A"
    chapters = detail.chapters_count or "Unknown"
    
    header = (
        f"{detail.title}\n"
        f"Year: {year}\n"
        f"Genres: {genres}\n"
        f"Chapters: {chapters}\n"
        f"Rating: {rating}\n\n"
    )
    
    # Truncate description to fit Telegram's 1024 char limit for captions
    available_length = max_length - len(header)
    description = detail.description or ""
    if len(description) > available_length:
        description = description[:available_length - 3] + "..."
    
    return header + description


@router.callback_query(F.data.startswith("fav:"))
async def handle_favorite(callback: CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return
    action, manga_id_text = callback.data.split(":")[1:]
    manga_id = int(manga_id_text)
    store = _get_favorites()
    client = _get_client()
    user_id = callback.from_user.id

    if action == "add":
        detail = await _run_sync(client.get_manga_detail, manga_id)
        store.add(user_id, manga_id, detail.title, detail.cover)
        new_action = "remove"
        new_text = "Remove Favorite"
        await callback.answer("✅ Added to favorites!")
    else:
        store.remove(user_id, manga_id)
        new_action = "add"
        new_text = "Add Favorite"
        await callback.answer("❌ Removed from favorites!")
    
    # Update the button in place
    new_buttons = [
        [InlineKeyboardButton(text="Chapters", callback_data=f"chapters:{manga_id}:1")],
        [InlineKeyboardButton(text=new_text, callback_data=f"fav:{new_action}:{manga_id}")],
    ]
    try:
        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_buttons))
    except Exception:
        pass


@router.callback_query(F.data.startswith("chapters:"))
async def show_chapters(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    _, manga_id_text, page_text = callback.data.split(":")
    manga_id = int(manga_id_text)
    page = int(page_text)

    client = _get_client()
    chapters = await _run_sync(client.get_manga_chapters, manga_id)
    if not chapters:
        await callback.message.edit_text("No chapters available.")
        return

    keyboard = _build_chapter_keyboard(chapters, manga_id, page)
    try:
        await callback.message.edit_text("Select a chapter:", reply_markup=keyboard)
    except Exception:
        # If message can't be edited (e.g., it's a photo), send new one
        await callback.message.answer("Select a chapter:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("goto_ch:"))
async def prompt_chapter_number(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return
    manga_id = int(callback.data.split(":")[1])
    
    # Save manga_id in state
    await state.set_state(ChapterStates.waiting_chapter_number)
    await state.update_data(manga_id=manga_id)
    
    client = _get_client()
    chapters = await _run_sync(client.get_manga_chapters, manga_id)
    
    # Find min and max chapter numbers
    ch_numbers = []
    for ch in chapters:
        num = ch.get("ch") or ch.get("chapter") or ch.get("number")
        if num:
            try:
                ch_numbers.append(float(num))
            except (ValueError, TypeError):
                pass
    
    if ch_numbers:
        min_ch = min(ch_numbers)
        max_ch = max(ch_numbers)
        hint = f"Available chapters: {min_ch} - {max_ch}"
    else:
        hint = ""
    
    try:
        await callback.message.edit_text(
            f"🔢 Enter chapter number:\n{hint}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Cancel", callback_data=f"chapters:{manga_id}:1")]
            ])
        )
    except Exception:
        await callback.message.answer(f"🔢 Enter chapter number:\n{hint}")


@router.message(ChapterStates.waiting_chapter_number)
async def handle_chapter_number_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    manga_id = data.get("manga_id")
    await state.clear()
    
    if not manga_id:
        await message.answer("Something went wrong. Please try again.")
        return
    
    # Parse the input
    chapter_input = message.text.strip()
    
    client = _get_client()
    chapters = await _run_sync(client.get_manga_chapters, manga_id)
    
    # Find chapter by number
    found_chapter = None
    for ch in chapters:
        ch_num = ch.get("ch") or ch.get("chapter") or ch.get("number")
        if ch_num and str(ch_num) == chapter_input:
            found_chapter = ch
            break
    
    if not found_chapter:
        # Try partial match (e.g., "100" matches "100.5")
        for ch in chapters:
            ch_num = ch.get("ch") or ch.get("chapter") or ch.get("number")
            if ch_num and str(ch_num).startswith(chapter_input):
                found_chapter = ch
                break
    
    if not found_chapter:
        try:
            await message.edit_text(
                f"❌ Chapter {chapter_input} not found.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📚 Back to chapters", callback_data=f"chapters:{manga_id}:1")]
                ])
            )
        except Exception:
            await message.answer(
                f"❌ Chapter {chapter_input} not found.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📚 Back to chapters", callback_data=f"chapters:{manga_id}:1")]
                ])
            )
        return
    
    # Found the chapter, now show format choice
    chapter_id = found_chapter.get("id")
    chapter_name = _chapter_title(found_chapter)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📕 PDF", callback_data=f"dl_pdf:{manga_id}:{chapter_id}"),
            InlineKeyboardButton(text="🗂 ZIP", callback_data=f"dl_zip:{manga_id}:{chapter_id}"),
        ],
        [InlineKeyboardButton(text="◀ Back", callback_data=f"chapters:{manga_id}:1")]
    ])
    
    await message.answer(
        f"📚 {chapter_name}\n\nChoose download format:",
        reply_markup=keyboard
    )


def _download_image(url: str) -> Image.Image | None:
    """Download image from URL and return PIL Image."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://desu.uno/",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert("RGB")
    except Exception as e:
        logger.error(f"Failed to download image {url}: {e}")
        return None


def _create_pdf_from_images(images: list[Image.Image], output_path: str) -> None:
    """Create PDF from list of PIL Images."""
    if not images:
        return
    images[0].save(output_path, save_all=True, append_images=images[1:], format="PDF")


def _create_zip_from_images(images: list[Image.Image], output_path: str) -> None:
    """Create ZIP archive from list of PIL Images."""
    if not images:
        return
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, img in enumerate(images, 1):
            img_buffer = io.BytesIO()
            img.save(img_buffer, format="JPEG", quality=95)
            img_buffer.seek(0)
            zf.writestr(f"page_{i:03d}.jpg", img_buffer.read())


async def _download_chapter_as_pdf(pages: list[dict], chapter_name: str) -> str | None:
    """Download all pages and create PDF. Returns path to PDF file."""
    images: list[Image.Image] = []
    
    for page in pages:
        url = page.get("img") or page.get("image") or page.get("url")
        if not url:
            continue
        img = await _run_sync(_download_image, url)
        if img:
            images.append(img)
    
    if not images:
        return None
    
    # Create temp PDF file
    temp_dir = tempfile.gettempdir()
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in chapter_name)
    pdf_path = os.path.join(temp_dir, f"{safe_name}.pdf")
    
    await _run_sync(_create_pdf_from_images, images, pdf_path)
    return pdf_path


async def _download_chapter_as_zip(pages: list[dict], chapter_name: str) -> str | None:
    """Download all pages and create ZIP. Returns path to ZIP file."""
    images: list[Image.Image] = []
    
    for page in pages:
        url = page.get("img") or page.get("image") or page.get("url")
        if not url:
            continue
        img = await _run_sync(_download_image, url)
        if img:
            images.append(img)
    
    if not images:
        return None
    
    # Create temp ZIP file
    temp_dir = tempfile.gettempdir()
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in chapter_name)
    zip_path = os.path.join(temp_dir, f"{safe_name}.zip")
    
    await _run_sync(_create_zip_from_images, images, zip_path)
    return zip_path


@router.callback_query(F.data.startswith("chapter:"))
async def show_chapter_pages(callback: CallbackQuery) -> None:
    """Show format choice for chapter download."""
    await callback.answer()
    if not callback.message:
        return
    _, manga_id_text, chapter_id_text = callback.data.split(":")
    manga_id = int(manga_id_text)
    chapter_id = int(chapter_id_text)

    client = _get_client()
    
    # Get chapter info for the name
    chapters = await _run_sync(client.get_manga_chapters, manga_id)
    chapter_info = next((ch for ch in chapters if ch.get("id") == chapter_id), {})
    chapter_name = _chapter_title(chapter_info) or f"Chapter_{chapter_id}"
    
    # Show format choice
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📕 PDF", callback_data=f"dl_pdf:{manga_id}:{chapter_id}"),
            InlineKeyboardButton(text="🗂 ZIP", callback_data=f"dl_zip:{manga_id}:{chapter_id}"),
        ],
        [InlineKeyboardButton(text="◀ Back", callback_data=f"chapters:{manga_id}:1")]
    ])
    
    try:
        await callback.message.edit_text(
            f"📚 {chapter_name}\n\nChoose download format:",
            reply_markup=keyboard
        )
    except Exception:
        await callback.message.answer(
            f"📚 {chapter_name}\n\nChoose download format:",
            reply_markup=keyboard
        )


@router.callback_query(F.data.startswith("dl_pdf:"))
async def download_as_pdf(callback: CallbackQuery) -> None:
    """Download chapter as PDF."""
    await callback.answer()
    if not callback.message:
        return
    _, manga_id_text, chapter_id_text = callback.data.split(":")
    manga_id = int(manga_id_text)
    chapter_id = int(chapter_id_text)

    store = _get_favorites()
    client = _get_client()
    
    # Get chapter info
    chapters = await _run_sync(client.get_manga_chapters, manga_id)
    chapter_info = next((ch for ch in chapters if ch.get("id") == chapter_id), {})
    chapter_name = _chapter_title(chapter_info) or f"Chapter_{chapter_id}"
    
    # Get manga title
    detail = await _run_sync(client.get_manga_detail, manga_id)
    manga_title = detail.title if detail else "Manga"
    file_name = f"{manga_title} - {chapter_name}.pdf"
    
    # Check cache first
    cached_file_id = store.get_cached_file(manga_id, chapter_id, "pdf")
    if cached_file_id:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer_document(cached_file_id, caption=f"📕 {manga_title} - {chapter_name}")
        store.mark_chapter_read(callback.from_user.id, manga_id, chapter_id, chapter_name)
        return
    
    # Show progress
    try:
        await callback.message.edit_text(f"⏳ Downloading {chapter_name} as PDF... Please wait.")
    except Exception:
        pass
    
    pages = await _run_sync(client.get_chapter_pages, manga_id, chapter_id)
    if not pages:
        try:
            await callback.message.edit_text("No pages found for this chapter.")
        except Exception:
            pass
        return
    
    pdf_path = await _download_chapter_as_pdf(pages, f"{manga_title} - {chapter_name}")
    
    if not pdf_path or not os.path.exists(pdf_path):
        try:
            await callback.message.edit_text("❌ Failed to create PDF.")
        except Exception:
            pass
        return
    
    try:
        from aiogram.types import FSInputFile
        pdf_file = FSInputFile(pdf_path, filename=file_name)
        try:
            await callback.message.delete()
        except Exception:
            pass
        sent_msg = await callback.message.answer_document(pdf_file, caption=f"📕 {manga_title} - {chapter_name}")
        
        # Cache the file_id for future use
        if sent_msg.document:
            store.cache_file(manga_id, chapter_id, "pdf", sent_msg.document.file_id, file_name)
        
        # Mark chapter as read
        store.mark_chapter_read(callback.from_user.id, manga_id, chapter_id, chapter_name)
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


@router.callback_query(F.data.startswith("dl_zip:"))
async def download_as_zip(callback: CallbackQuery) -> None:
    """Download chapter as ZIP."""
    await callback.answer()
    if not callback.message:
        return
    _, manga_id_text, chapter_id_text = callback.data.split(":")
    manga_id = int(manga_id_text)
    chapter_id = int(chapter_id_text)

    store = _get_favorites()
    client = _get_client()
    
    # Get chapter info
    chapters = await _run_sync(client.get_manga_chapters, manga_id)
    chapter_info = next((ch for ch in chapters if ch.get("id") == chapter_id), {})
    chapter_name = _chapter_title(chapter_info) or f"Chapter_{chapter_id}"
    
    # Get manga title
    detail = await _run_sync(client.get_manga_detail, manga_id)
    manga_title = detail.title if detail else "Manga"
    file_name = f"{manga_title} - {chapter_name}.zip"
    
    # Check cache first
    cached_file_id = store.get_cached_file(manga_id, chapter_id, "zip")
    if cached_file_id:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer_document(cached_file_id, caption=f"🗂 {manga_title} - {chapter_name}")
        store.mark_chapter_read(callback.from_user.id, manga_id, chapter_id, chapter_name)
        return
    
    # Show progress
    try:
        await callback.message.edit_text(f"⏳ Downloading {chapter_name} as ZIP... Please wait.")
    except Exception:
        pass
    
    pages = await _run_sync(client.get_chapter_pages, manga_id, chapter_id)
    if not pages:
        try:
            await callback.message.edit_text("No pages found for this chapter.")
        except Exception:
            pass
        return
    
    zip_path = await _download_chapter_as_zip(pages, f"{manga_title} - {chapter_name}")
    
    if not zip_path or not os.path.exists(zip_path):
        try:
            await callback.message.edit_text("❌ Failed to create ZIP.")
        except Exception:
            pass
        return
    
    try:
        from aiogram.types import FSInputFile
        zip_file = FSInputFile(zip_path, filename=file_name)
        try:
            await callback.message.delete()
        except Exception:
            pass
        sent_msg = await callback.message.answer_document(zip_file, caption=f"🗂 {manga_title} - {chapter_name}")
        
        # Cache the file_id for future use
        if sent_msg.document:
            store.cache_file(manga_id, chapter_id, "zip", sent_msg.document.file_id, file_name)
        
        # Mark chapter as read
        store.mark_chapter_read(callback.from_user.id, manga_id, chapter_id, chapter_name)
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)


def _get_token() -> str:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is not set")
    return token


def _get_base_url() -> str:
    return os.getenv("DESU_BASE_URL", "https://desu.uno")


def _get_admin_id() -> int | None:
    """Get admin Telegram ID from environment."""
    admin_id = os.getenv("ADMIN_ID")
    return int(admin_id) if admin_id else None


def _is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    admin_id = _get_admin_id()
    return admin_id is not None and user_id == admin_id


async def main() -> None:
    global CLIENT, FAVORITES

    load_dotenv()
    token = _get_token()
    CLIENT = DesuClient(_get_base_url())
    FAVORITES = FavoritesStore()

    bot = Bot(token)
    storage = MemoryStorage()
    dispatcher = Dispatcher(storage=storage)
    dispatcher.include_router(router)

    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
