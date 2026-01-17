from __future__ import annotations

import logging
import os
from typing import Iterable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from dotenv import load_dotenv

from desu_client import DesuClient, MangaDetail
from favorites import FavoritesStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAIN_MENU = ReplyKeyboardMarkup(
    [["Profile", "Catalog", "Search"]],
    resize_keyboard=True,
)


def _build_search_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Genres", callback_data="search:genres")],
            [InlineKeyboardButton("Keywords", callback_data="search:keywords")],
            [InlineKeyboardButton("New Releases", callback_data="search:new")],
            [InlineKeyboardButton("Popular", callback_data="search:popular")],
        ]
    )


def _build_catalog_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("New Releases", callback_data="search:new")],
            [InlineKeyboardButton("Popular", callback_data="search:popular")],
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
        row.append(InlineKeyboardButton(label, callback_data=f"chapter:{manga_id}:{chapter_id}"))
        if len(row) == columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    navigation: list[InlineKeyboardButton] = []
    if start > 0:
        navigation.append(
            InlineKeyboardButton("◀ Prev", callback_data=f"chapters:{manga_id}:{page - 1}")
        )
    if end < len(chapters):
        navigation.append(
            InlineKeyboardButton("Next ▶", callback_data=f"chapters:{manga_id}:{page + 1}")
        )
    if navigation:
        rows.append(navigation)

    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to the Desu manga bot!", reply_markup=MAIN_MENU
    )


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store: FavoritesStore = context.bot_data["favorites"]
    user_id = update.effective_user.id
    favorites = list(store.list(user_id))

    if not favorites:
        await update.message.reply_text("You have no favorites yet.")
        return

    keyboard = [
        [InlineKeyboardButton(title, callback_data=f"manga:{manga_id}")]
        for manga_id, title, _cover in favorites
    ]
    await update.message.reply_text(
        "Your favorites:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Browse the catalog:", reply_markup=_build_catalog_menu()
    )


async def show_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Choose how to search:", reply_markup=_build_search_menu()
    )


async def prompt_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    context.user_data["search_mode"] = "keywords"
    await update.callback_query.message.reply_text(
        "Send keywords to search (e.g. 'dungeon hero')."
    )


async def prompt_genres(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    context.user_data["search_mode"] = "genres"
    await update.callback_query.message.reply_text(
        "Send genres separated by commas (e.g. 'action, fantasy')."
    )


async def run_quick_search(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, popularity: bool = False, is_new: bool = False
) -> None:
    await update.callback_query.answer()
    client: DesuClient = context.bot_data["client"]
    results = client.search_manga(popularity=popularity, is_new=is_new)
    await _send_search_results(update.callback_query.message, results)


async def search_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mode = context.user_data.pop("search_mode", None)
    if not mode:
        return
    client: DesuClient = context.bot_data["client"]
    if mode == "keywords":
        results = client.search_manga(keywords=update.message.text)
    else:
        genres = [genre.strip() for genre in update.message.text.split(",") if genre.strip()]
        results = client.search_manga(genres=genres)
    await _send_search_results(update.message, results)


async def _send_search_results(target, results: list) -> None:
    if not results:
        await target.reply_text("No results found.")
        return
    keyboard = [
        [InlineKeyboardButton(result.title, callback_data=f"manga:{result.id}")]
        for result in results[:10]
    ]
    await target.reply_text(
        "Select a manga:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_manga(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    manga_id = int(query.data.split(":")[1])
    client: DesuClient = context.bot_data["client"]
    store: FavoritesStore = context.bot_data["favorites"]

    detail = client.get_manga_detail(manga_id)
    is_favorite = store.has(update.effective_user.id, manga_id)

    description = _format_manga_detail(detail)
    buttons = [
        [InlineKeyboardButton("Chapters", callback_data=f"chapters:{manga_id}:1")],
        [
            InlineKeyboardButton(
                "Remove Favorite" if is_favorite else "Add Favorite",
                callback_data=f"fav:{'remove' if is_favorite else 'add'}:{manga_id}",
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    if detail.cover:
        await query.message.reply_photo(detail.cover, caption=description, reply_markup=reply_markup)
    else:
        await query.message.reply_text(description, reply_markup=reply_markup)


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


async def handle_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action, manga_id_text = query.data.split(":")[1:]
    manga_id = int(manga_id_text)
    store: FavoritesStore = context.bot_data["favorites"]
    client: DesuClient = context.bot_data["client"]
    user_id = update.effective_user.id

    if action == "add":
        detail = client.get_manga_detail(manga_id)
        store.add(user_id, manga_id, detail.title, detail.cover)
        await query.message.reply_text("Added to favorites.")
    else:
        store.remove(user_id, manga_id)
        await query.message.reply_text("Removed from favorites.")


async def show_chapters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, manga_id_text, page_text = query.data.split(":")
    manga_id = int(manga_id_text)
    page = int(page_text)

    client: DesuClient = context.bot_data["client"]
    chapters = client.get_manga_chapters(manga_id)
    if not chapters:
        await query.message.reply_text("No chapters available.")
        return

    keyboard = _build_chapter_keyboard(chapters, manga_id, page)
    await query.message.reply_text("Select a chapter:", reply_markup=keyboard)


async def show_chapter_pages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, manga_id_text, chapter_id_text = query.data.split(":")
    manga_id = int(manga_id_text)
    chapter_id = int(chapter_id_text)

    client: DesuClient = context.bot_data["client"]
    pages = client.get_chapter_pages(manga_id, chapter_id)
    if not pages:
        await query.message.reply_text("No pages found for this chapter.")
        return

    first_page = pages[0].get("image") or pages[0].get("url")
    await query.message.reply_text(
        f"Chapter has {len(pages)} pages. First page: {first_page}"
    )


def _get_token() -> str:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is not set")
    return token


def _get_base_url() -> str:
    return os.getenv("DESU_BASE_URL", "https://desu.me")


def main() -> None:
    load_dotenv()
    token = _get_token()
    client = DesuClient(_get_base_url())
    favorites = FavoritesStore()

    application = Application.builder().token(token).build()
    application.bot_data["client"] = client
    application.bot_data["favorites"] = favorites

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex("^Profile$"), show_profile))
    application.add_handler(MessageHandler(filters.Regex("^Catalog$"), show_catalog))
    application.add_handler(MessageHandler(filters.Regex("^Search$"), show_search))

    application.add_handler(CallbackQueryHandler(prompt_genres, pattern="^search:genres$"))
    application.add_handler(CallbackQueryHandler(prompt_keywords, pattern="^search:keywords$"))
    application.add_handler(
        CallbackQueryHandler(
            lambda u, c: run_quick_search(u, c, is_new=True), pattern="^search:new$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            lambda u, c: run_quick_search(u, c, popularity=True), pattern="^search:popular$"
        )
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_input))

    application.add_handler(CallbackQueryHandler(show_manga, pattern="^manga:\d+$"))
    application.add_handler(CallbackQueryHandler(handle_favorite, pattern="^fav:(add|remove):\d+$"))
    application.add_handler(CallbackQueryHandler(show_chapters, pattern="^chapters:\d+:\d+$"))
    application.add_handler(CallbackQueryHandler(show_chapter_pages, pattern="^chapter:\d+:\d+$"))

    application.run_polling()


if __name__ == "__main__":
    main()
