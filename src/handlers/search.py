"""Search handlers: keywords, genres, new, popular."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.filters import Command

from config import GENRES
from keyboards import build_genre_keyboard, build_search_results
from states import SearchStates
from dependencies import get_client
from utils import run_sync, safe_callback_answer

router = Router()

# Store search results in memory (per-user cache)
_search_cache: dict[int, tuple[str, str, list]] = {}  # user_id -> (search_type, query, results)


def _cache_results(user_id: int, search_type: str, query: str, results: list) -> None:
    """Cache search results for pagination."""
    _search_cache[user_id] = (search_type, query, results)


def _get_cached(user_id: int) -> tuple[str, str, list] | None:
    """Get cached search results."""
    return _search_cache.get(user_id)


@router.message(Command("new"))
async def cmd_new(message: Message) -> None:
    """Handle /new command - show new releases."""
    loading_msg = await message.answer("⏳ Загрузка новых релизов...")
    client = get_client()
    results = await run_sync(client.search_manga, is_new=True)
    _cache_results(message.from_user.id, "new", "", results)
    await _edit_search_results(loading_msg, results, "new", "")


@router.message(Command("popular"))
async def cmd_popular(message: Message) -> None:
    """Handle /popular command - show popular manga."""
    loading_msg = await message.answer("⏳ Загрузка популярной манги...")
    client = get_client()
    results = await run_sync(client.search_manga, popularity=True)
    _cache_results(message.from_user.id, "popular", "", results)
    await _edit_search_results(loading_msg, results, "popular", "")


@router.callback_query(F.data == "search:keywords")
async def prompt_keywords(callback: CallbackQuery, state: FSMContext) -> None:
    """Prompt user to enter keywords."""
    await safe_callback_answer(callback)
    await state.set_state(SearchStates.keywords)
    if callback.message:
        try:
            await callback.message.edit_text("Отправьте ключевые слова для поиска (например, 'Ван пис').")
        except Exception:
            await callback.message.answer("Отправьте ключевые слова для поиска (например, 'Ван пис').")


@router.callback_query(F.data == "search:genres")
async def prompt_genres(callback: CallbackQuery, state: FSMContext) -> None:
    """Show genre selection keyboard."""
    await safe_callback_answer(callback)
    if callback.message:
        try:
            await callback.message.edit_text(
                "Выберите жанр:",
                reply_markup=build_genre_keyboard(page=1)
            )
        except Exception:
            await callback.message.answer(
                "Выберите жанр:",
                reply_markup=build_genre_keyboard(page=1)
            )


@router.callback_query(F.data.startswith("genres_page:"))
async def show_genres_page(callback: CallbackQuery) -> None:
    """Handle genre pagination."""
    await safe_callback_answer(callback)
    if not callback.message:
        return
    page = int(callback.data.split(":")[1])
    try:
        await callback.message.edit_text(
            "Выберите жанр:",
            reply_markup=build_genre_keyboard(page=page)
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("genre:"))
async def search_by_genre(callback: CallbackQuery) -> None:
    """Search manga by selected genre."""
    await safe_callback_answer(callback)
    if not callback.message:
        return
    api_genre = callback.data.split(":", 1)[1]
    display_name = GENRES.get(api_genre, api_genre)
    
    try:
        await callback.message.edit_text(f"⏳ Поиск {display_name}...")
    except Exception:
        pass
    
    client = get_client()
    results = await run_sync(client.search_manga, genres=[api_genre])
    _cache_results(callback.from_user.id, "genre", api_genre, results)
    await _edit_search_results(callback.message, results, "genre", api_genre)


@router.callback_query(F.data.in_({"search:new", "search:popular"}))
async def run_quick_search(callback: CallbackQuery) -> None:
    """Handle new/popular quick search."""
    await safe_callback_answer(callback)
    client = get_client()
    popularity = callback.data == "search:popular"
    is_new = callback.data == "search:new"
    search_type = "popular" if popularity else "new"
    
    if callback.message:
        try:
            await callback.message.edit_text("⏳ Загрузка...")
        except Exception:
            pass
    
    results = await run_sync(client.search_manga, popularity=popularity, is_new=is_new)
    _cache_results(callback.from_user.id, search_type, "", results)
    if callback.message:
        await _edit_search_results(callback.message, results, search_type, "")


@router.message(SearchStates.keywords)
async def search_keywords(message: Message, state: FSMContext) -> None:
    """Search by keywords."""
    await state.clear()
    query = message.text or ""
    loading_msg = await message.answer("⏳ Поиск...")
    client = get_client()
    results = await run_sync(client.search_manga, keywords=query)
    _cache_results(message.from_user.id, "keywords", query, results)
    await _edit_search_results(loading_msg, results, "keywords", query)


@router.callback_query(F.data.startswith("results:"))
async def paginate_results(callback: CallbackQuery) -> None:
    """Handle search results pagination."""
    await safe_callback_answer(callback)
    if not callback.message:
        return
    
    # Parse: results:type:query:page
    parts = callback.data.split(":")
    if len(parts) < 4:
        return
    
    search_type = parts[1]
    # Query might contain colons, so join all middle parts
    page = int(parts[-1])
    query = ":".join(parts[2:-1])
    
    # Get cached results
    cached = _get_cached(callback.from_user.id)
    if not cached:
        await callback.message.edit_text("❌ Результаты устарели. Повторите поиск.")
        return
    
    cached_type, cached_query, results = cached
    
    # Verify it's the same search
    if cached_type != search_type or cached_query != query:
        await callback.message.edit_text("❌ Результаты устарели. Повторите поиск.")
        return
    
    try:
        await callback.message.edit_text(
            "Выберите мангу:", 
            reply_markup=build_search_results(results, page, search_type=search_type, search_query=query)
        )
    except Exception:
        pass


@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery) -> None:
    """Handle noop callback (page info button)."""
    await safe_callback_answer(callback)


async def _send_search_results(target: Message, results: list, search_type: str = "search", query: str = "") -> None:
    """Send search results as a new message."""
    if not results:
        await target.answer("Нет результатов.")
        return
    await target.answer("Выберите мангу:", reply_markup=build_search_results(results, search_type=search_type, search_query=query))


async def _edit_search_results(target: Message, results: list, search_type: str = "search", query: str = "") -> None:
    """Edit existing message with search results."""
    if not results:
        try:
            await target.edit_text("Нет результатов.")
        except Exception:
            await target.answer("Нет результатов.")
        return
    try:
        await target.edit_text("Выберите мангу:", reply_markup=build_search_results(results, search_type=search_type, search_query=query))
    except Exception:
        await target.answer("Выберите мангу:", reply_markup=build_search_results(results, search_type=search_type, search_query=query))
