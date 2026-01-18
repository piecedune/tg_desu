"""Base handlers: start, profile, catalog, search menu."""
from __future__ import annotations

import os
import sys

# Add parent directory to path for imports when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, FSInputFile, InputMediaPhoto

import config
from keyboards import (
    MAIN_MENU,
    build_catalog_menu,
    build_search_menu,
    build_profile_menu,
    build_favorites_keyboard,
    build_history_keyboard,
    build_settings_keyboard,
    build_manga_buttons,
)
from dependencies import get_favorites, get_client
from utils import run_sync, format_manga_detail

router = Router()

# Path to menu images
MENU_IMAGES_DIR = os.path.join(os.path.dirname(__file__), "..", "menu")

WELCOME_GUIDE = """
🎌 <b>Добро пожаловать в Desu Manga Bot!</b>

Твой персональный помощник для чтения манги.

<b>📚 Основные функции:</b>

🔍 <b>Поиск</b> — поиск манги по названию, жанрам или в каталоге новинок и популярных

📚 <b>Каталог</b> — быстрый доступ к новинкам и популярной манге

👤 <b>Профиль</b> — твоя статистика, избранное, история и настройки

🎲 <b>Случайная</b> — открой случайную мангу, если не знаешь что почитать

<b>📖 Как читать:</b>
1. Найди мангу через поиск или каталог
2. Нажми на неё, чтобы увидеть описание
3. Выбери главу из списка
4. Читай прямо в чате или скачай PDF/ZIP

<b>⭐ Избранное:</b>
Добавляй мангу в избранное — бот пришлёт уведомление о новых главах!

<b>✅ Прочитанное:</b>
Бот отмечает прочитанные главы галочкой ✅

Приятного чтения! 🍵
"""


def get_random_menu_image() -> str | None:
    """Get a random image from menu folder."""
    import random
    image_files = []
    for i in range(1, 6):
        img_path = os.path.join(MENU_IMAGES_DIR, f"{i}.jpg")
        if os.path.exists(img_path):
            image_files.append(img_path)
    return random.choice(image_files) if image_files else None


@router.message(CommandStart(deep_link=True))
async def start_with_link(message: Message, command: CommandObject) -> None:
    """Handle /start with deep link (e.g., /start manga_12345)."""
    store = get_favorites()
    user = message.from_user
    store.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    
    args = command.args
    if args and args.startswith("manga_"):
        try:
            manga_id = int(args.replace("manga_", ""))
            client = get_client()
            
            await message.answer("⏳ Загружаю мангу...", reply_markup=MAIN_MENU)
            
            detail = await run_sync(client.get_manga_detail, manga_id)
            if not detail:
                await message.answer("Манга не найдена.", reply_markup=MAIN_MENU)
                return
            
            is_favorite = store.has(user.id, manga_id)
            store.add_manga_to_history(user.id, manga_id, detail.title, detail.cover)
            
            description = format_manga_detail(detail)
            reply_markup = build_manga_buttons(manga_id, is_favorite, config.BOT_USERNAME)
            
            if detail.cover:
                await message.answer_photo(detail.cover, caption=description, reply_markup=reply_markup)
            else:
                await message.answer(description, reply_markup=reply_markup)
            return
        except (ValueError, Exception):
            pass
    
    # Default: show welcome guide
    await message.answer(WELCOME_GUIDE, reply_markup=MAIN_MENU, parse_mode="HTML")


@router.message(CommandStart())
async def start(message: Message) -> None:
    """Handle /start command without arguments."""
    store = get_favorites()
    user = message.from_user
    store.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    await message.answer(WELCOME_GUIDE, reply_markup=MAIN_MENU, parse_mode="HTML")


@router.message(Command("search"))
async def cmd_search(message: Message) -> None:
    """Handle /search command."""
    await message.answer("Выберите способ поиска:", reply_markup=build_search_menu())


def _build_profile_text(user, stats: dict, download_format: str) -> str:
    """Build profile text message."""
    username = f"@{user.username}" if user.username else user.first_name
    format_display = "PDF" if download_format == "pdf" else "ZIP"
    
    return (
        f"👤 <b>Твой Профиль</b>\n"
        f"Пользователь: {username}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"⭐ Избранное: {stats['favorites_count']} манг\n"
        f"📖 Прочитано глав: {stats['chapters_read']}\n"
        f"📚 Просмотрено манги: {stats['manga_read']}\n"
        f"📅 Дней с регистрации: {stats['days_registered']}\n\n"
        f"🏅 <b>Звание:</b> {stats['rank']}\n\n"
        f"⚙️ <b>Настройки:</b>\n"
        f"📥 Формат скачивания: {format_display}"
    )


@router.message(F.text == "👤 Профиль")
async def show_profile(message: Message) -> None:
    """Show user's profile with stats."""
    store = get_favorites()
    user_id = message.from_user.id
    
    # Update last active
    store.add_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name
    )
    
    stats = store.get_user_profile_stats(user_id)
    download_format = store.get_download_format(user_id)
    
    text = _build_profile_text(message.from_user, stats, download_format)
    await message.answer(text, reply_markup=build_profile_menu(), parse_mode="HTML")


@router.callback_query(F.data == "profile:main")
async def profile_main(callback: CallbackQuery) -> None:
    """Return to main profile view."""
    store = get_favorites()
    user_id = callback.from_user.id
    
    stats = store.get_user_profile_stats(user_id)
    download_format = store.get_download_format(user_id)
    
    text = _build_profile_text(callback.from_user, stats, download_format)
    await callback.message.edit_text(text, reply_markup=build_profile_menu(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "profile:favorites")
async def profile_favorites(callback: CallbackQuery) -> None:
    """Show user's favorites list."""
    store = get_favorites()
    user_id = callback.from_user.id
    favorites_raw = list(store.list(user_id))
    
    if not favorites_raw:
        await callback.message.edit_text(
            "⭐ <b>Избранное</b>\n\nУ тебя пока нет избранных манг.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 В профиль", callback_data="profile:main")]
            ]),
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    favorites = [{"manga_id": m_id, "title": title, "cover": cover} for m_id, title, cover in favorites_raw]
    text = f"⭐ <b>Избранное</b> ({len(favorites)} манг)"
    await callback.message.edit_text(
        text,
        reply_markup=build_favorites_keyboard(favorites, page=1),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fav_page:"))
async def favorites_page(callback: CallbackQuery) -> None:
    """Navigate favorites pages."""
    page = int(callback.data.split(":")[1])
    store = get_favorites()
    user_id = callback.from_user.id
    favorites_raw = list(store.list(user_id))
    favorites = [{"manga_id": m_id, "title": title, "cover": cover} for m_id, title, cover in favorites_raw]
    
    text = f"⭐ <b>Избранное</b> ({len(favorites)} манг)"
    await callback.message.edit_text(
        text,
        reply_markup=build_favorites_keyboard(favorites, page=page),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "profile:history")
async def profile_history(callback: CallbackQuery) -> None:
    """Show user's viewing history."""
    store = get_favorites()
    user_id = callback.from_user.id
    history = store.get_recent_manga(user_id, limit=50)
    
    if not history:
        await callback.message.edit_text(
            "📖 <b>История просмотров</b>\n\nТы ещё не просматривал манги.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 В профиль", callback_data="profile:main")]
            ]),
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    text = f"📖 <b>История просмотров</b> (последние {len(history)})"
    await callback.message.edit_text(
        text,
        reply_markup=build_history_keyboard(history, page=1),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("history_page:"))
async def history_page(callback: CallbackQuery) -> None:
    """Navigate history pages."""
    page = int(callback.data.split(":")[1])
    store = get_favorites()
    user_id = callback.from_user.id
    history = store.get_recent_manga(user_id, limit=50)
    
    text = f"📖 <b>История просмотров</b> (последние {len(history)})"
    await callback.message.edit_text(
        text,
        reply_markup=build_history_keyboard(history, page=page),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "profile:settings")
async def profile_settings(callback: CallbackQuery) -> None:
    """Show user settings."""
    store = get_favorites()
    user_id = callback.from_user.id
    current_format = store.get_download_format(user_id)
    
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        "📥 <b>Формат скачивания по умолчанию:</b>\n"
        "Выбери формат, в котором будут скачиваться главы."
    )
    await callback.message.edit_text(
        text,
        reply_markup=build_settings_keyboard(current_format),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_format:"))
async def set_format(callback: CallbackQuery) -> None:
    """Set download format preference."""
    new_format = callback.data.split(":")[1]
    store = get_favorites()
    user_id = callback.from_user.id
    
    store.set_download_format(user_id, new_format)
    
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        "📥 <b>Формат скачивания по умолчанию:</b>\n"
        f"✅ Формат изменён на {new_format.upper()}"
    )
    await callback.message.edit_text(
        text,
        reply_markup=build_settings_keyboard(new_format),
        parse_mode="HTML"
    )
    await callback.answer(f"Формат изменён на {new_format.upper()}")


@router.message(F.text == "📚 Каталог")
async def show_catalog(message: Message) -> None:
    """Show catalog menu with random image."""
    img_path = get_random_menu_image()
    if img_path:
        await message.answer_photo(
            FSInputFile(img_path),
            caption="📚 <b>Каталог</b>\n\nВыбери раздел:",
            reply_markup=build_catalog_menu(),
            parse_mode="HTML"
        )
    else:
        await message.answer("📚 <b>Каталог</b>\n\nВыбери раздел:", reply_markup=build_catalog_menu(), parse_mode="HTML")


@router.message(F.text == "🔍 Поиск")
async def show_search(message: Message) -> None:
    """Show search menu with random image."""
    img_path = get_random_menu_image()
    if img_path:
        await message.answer_photo(
            FSInputFile(img_path),
            caption="🔍 <b>Поиск</b>\n\nКак будем искать?",
            reply_markup=build_search_menu(),
            parse_mode="HTML"
        )
    else:
        await message.answer("🔍 <b>Поиск</b>\n\nКак будем искать?", reply_markup=build_search_menu(), parse_mode="HTML")


@router.message(F.text == "🎲 Случайная")
async def show_random_manga(message: Message) -> None:
    """Show a random manga."""
    import random
    
    store = get_favorites()
    client = get_client()
    user = message.from_user
    
    store.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    
    await message.answer("🎲 Ищу случайную мангу...")
    
    # Try random manga IDs (1-6965)
    for _ in range(5):  # Try up to 5 times
        try:
            manga_id = random.randint(1, 6965)
            detail = await run_sync(client.get_manga_detail, manga_id)
            
            if detail and detail.title:
                is_favorite = store.has(user.id, manga_id)
                store.add_manga_to_history(user.id, manga_id, detail.title, detail.cover)
                
                description = format_manga_detail(detail)
                reply_markup = build_manga_buttons(manga_id, is_favorite, config.BOT_USERNAME)
                
                if detail.cover:
                    await message.answer_photo(detail.cover, caption=description, reply_markup=reply_markup)
                else:
                    await message.answer(description, reply_markup=reply_markup)
                return
        except Exception as e:
            store.log_error("random_manga", str(e), f"manga_id={manga_id}")
            continue
    
    await message.answer("😔 Не удалось найти случайную мангу. Попробуй ещё раз!")
