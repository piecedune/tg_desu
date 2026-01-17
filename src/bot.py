from __future__ import annotations

import asyncio
import logging
import os
from typing import Iterable

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
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
    genres = State()


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


def _chapter_title(chapter: dict) -> str:
    number = chapter.get("chapter") or chapter.get("number")
    title = chapter.get("title")
    if number and title:
        return f"{number} {title}"
    if number:
        return str(number)
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

    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer("Welcome to the Desu manga bot!", reply_markup=MAIN_MENU)


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
        await callback.message.answer("Send keywords to search (e.g. 'dungeon hero').")


@router.callback_query(F.data == "search:genres")
async def prompt_genres(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SearchStates.genres)
    if callback.message:
        await callback.message.answer("Send genres separated by commas (e.g. 'action, fantasy').")


@router.callback_query(F.data.in_({"search:new", "search:popular"}))
async def run_quick_search(callback: CallbackQuery) -> None:
    await callback.answer()
    client = _get_client()
    popularity = callback.data == "search:popular"
    is_new = callback.data == "search:new"
    results = await _run_sync(client.search_manga, popularity=popularity, is_new=is_new)
    if callback.message:
        await _send_search_results(callback.message, results)


@router.message(SearchStates.keywords)
async def search_keywords(message: Message, state: FSMContext) -> None:
    await state.clear()
    client = _get_client()
    results = await _run_sync(client.search_manga, keywords=message.text)
    await _send_search_results(message, results)


@router.message(SearchStates.genres)
async def search_genres(message: Message, state: FSMContext) -> None:
    await state.clear()
    client = _get_client()
    genres = [genre.strip() for genre in message.text.split(",") if genre.strip()]
    results = await _run_sync(client.search_manga, genres=genres)
    await _send_search_results(message, results)


async def _send_search_results(target: Message, results: list) -> None:
    if not results:
        await target.answer("No results found.")
        return
    keyboard = [
        [InlineKeyboardButton(text=result.title, callback_data=f"manga:{result.id}")]
        for result in results[:10]
    ]
    await target.answer("Select a manga:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data.startswith("manga:"))
async def show_manga(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    manga_id = int(callback.data.split(":")[1])
    client = _get_client()
    store = _get_favorites()

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

    if detail.cover:
        await callback.message.answer_photo(detail.cover, caption=description, reply_markup=reply_markup)
    else:
        await callback.message.answer(description, reply_markup=reply_markup)


def _format_manga_detail(detail: MangaDetail) -> str:
    genres = ", ".join(detail.genres) if detail.genres else "Unknown"
    year = detail.year or "Unknown"
    rating = detail.rating or "N/A"
    chapters = detail.chapters_count or "Unknown"
    return (
        f"{detail.title}\n"
        f"Year: {year}\n"
        f"Genres: {genres}\n"
        f"Chapters: {chapters}\n"
        f"Rating: {rating}\n\n"
        f"{detail.description}"
    )


@router.callback_query(F.data.startswith("fav:"))
async def handle_favorite(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    action, manga_id_text = callback.data.split(":")[1:]
    manga_id = int(manga_id_text)
    store = _get_favorites()
    client = _get_client()
    user_id = callback.from_user.id

    if action == "add":
        detail = await _run_sync(client.get_manga_detail, manga_id)
        store.add(user_id, manga_id, detail.title, detail.cover)
        await callback.message.answer("Added to favorites.")
    else:
        store.remove(user_id, manga_id)
        await callback.message.answer("Removed from favorites.")


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
        await callback.message.answer("No chapters available.")
        return

    keyboard = _build_chapter_keyboard(chapters, manga_id, page)
    await callback.message.answer("Select a chapter:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("chapter:"))
async def show_chapter_pages(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    _, manga_id_text, chapter_id_text = callback.data.split(":")
    manga_id = int(manga_id_text)
    chapter_id = int(chapter_id_text)

    client = _get_client()
    pages = await _run_sync(client.get_chapter_pages, manga_id, chapter_id)
    if not pages:
        await callback.message.answer("No pages found for this chapter.")
        return

    first_page = pages[0].get("image") or pages[0].get("url")
    await callback.message.answer(
        f"Chapter has {len(pages)} pages. First page: {first_page}"
    )


def _get_token() -> str:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is not set")
    return token


def _get_base_url() -> str:
    return os.getenv("DESU_BASE_URL", "https://desu.me")


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
