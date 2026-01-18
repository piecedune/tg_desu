"""Admin handlers: broadcast, stats, backup, errors."""
from __future__ import annotations

import asyncio
import logging
import os

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import is_admin
from keyboards import MAIN_MENU
from states import BroadcastStates
from dependencies import get_favorites
from utils import safe_callback_answer

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Cancel current operation."""
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await message.answer("Операция отменена.", reply_markup=MAIN_MENU)
    else:
        await message.answer("Нечего отменять.")


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Admin command to show bot statistics."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для использования этой команды.")
        return
    
    store = get_favorites()
    stats = store.get_stats()
    
    await message.answer(
        f"📊 Статистика бота\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"🟢 Активных (7 дней): {stats['active_users_7d']}\n"
        f"⭐ Всего в избранном: {stats['total_favorites']}\n"
        f"📖 Прочитано глав: {stats['total_chapter_reads']}\n"
        f"📦 Кэшированных файлов: {stats['cached_files']}",
        parse_mode=None
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    """Admin command to start broadcast."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для использования этой команды.")
        return
    
    store = get_favorites()
    user_count = store.get_user_count()
    
    await state.set_state(BroadcastStates.waiting_content)
    await message.answer(
        f"📢 Режим рассылки\n\n"
        f"Всего пользователей: {user_count}\n\n"
        f"Отправьте мне содержимое для рассылки:\n"
        f"- Текстовое сообщение\n"
        f"- Фото с подписью\n\n"
        f"Используйте /cancel для отмены.",
        parse_mode=None
    )


@router.message(BroadcastStates.waiting_content)
async def handle_broadcast_content(message: Message, state: FSMContext) -> None:
    """Handle broadcast content from admin."""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    
    if message.photo:
        await state.update_data(
            content_type="photo",
            photo_id=message.photo[-1].file_id,
            caption=message.caption or ""
        )
    elif message.text:
        await state.update_data(
            content_type="text",
            text=message.text
        )
    else:
        await message.answer("❌ Пожалуйста, отправьте текст или фото с подписью.")
        return
    
    await state.set_state(BroadcastStates.confirm)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить и отправить", callback_data="broadcast:confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast:cancel"),
        ]
    ])
    
    store = get_favorites()
    user_count = store.get_user_count()
    
    await message.answer(
        f"📢 Готово к рассылке {user_count} пользователям.\n\nПодтвердить?",
        reply_markup=keyboard,
        parse_mode=None
    )


@router.callback_query(F.data == "broadcast:confirm")
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm and send broadcast."""
    await safe_callback_answer(callback)
    
    if not is_admin(callback.from_user.id):
        await state.clear()
        return
    
    if not callback.message:
        return
    
    data = await state.get_data()
    await state.clear()
    
    content_type = data.get("content_type")
    if not content_type:
        await callback.message.edit_text("❌ Нет содержимого для рассылки.")
        return
    
    store = get_favorites()
    users = store.get_all_users()
    
    await callback.message.edit_text(f"📤 Рассылка {len(users)} пользователям...")
    
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
        
        await asyncio.sleep(0.05)
    
    await callback.message.edit_text(
        f"✅ Рассылка завершена!\n\n"
        f"Отправлено: {success}\n"
        f"Не удалось отправить: {failed}",
        parse_mode=None
    )


@router.callback_query(F.data == "broadcast:cancel")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel broadcast."""
    await callback.answer("Рассылка отменена.")
    await state.clear()
    if callback.message:
        await callback.message.edit_text("❌ Рассылка отменена.")


@router.message(Command("backup"))
async def cmd_backup(message: Message) -> None:
    """Admin command to get database backup."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для использования этой команды.")
        return
    
    store = get_favorites()
    db_path = str(store.db_path)
    
    if not os.path.exists(db_path):
        await message.answer("❌ Файл базы данных не найден.")
        return
    
    try:
        db_file = FSInputFile(db_path, filename="favorites_backup.db")
        await message.answer_document(
            db_file,
            caption=f"🗄 Резервная копия базы данных\n📅 {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        await message.answer(f"❌ Ошибка резервного копирования: {e}")


@router.message(Command("errors"))
async def cmd_errors(message: Message) -> None:
    """Admin command to view recent errors."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для использования этой команды.")
        return
    
    store = get_favorites()
    errors = store.get_recent_errors(limit=20)
    
    if not errors:
        await message.answer("✅ Нет зарегистрированных ошибок.")
        return
    
    text = "🐛 <b>Недавние ошибки</b>\n\n"
    for err in errors[:10]:
        text += (
            f"<b>{err['error_type']}</b>\n"
            f"<code>{err['error_message'][:100]}</code>\n"
            f"📅 {err['created_at']}\n\n"
        )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Очистить старые ошибки", callback_data="admin:clear_errors")]
    ])
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "admin:clear_errors")
async def clear_errors(callback: CallbackQuery) -> None:
    """Clear old error logs."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен.")
        return
    
    store = get_favorites()
    deleted = store.clear_old_errors(days=7)
    
    await callback.answer(f"✅ Удалено {deleted} старых ошибок")
    await callback.message.edit_text(f"✅ Очистка {deleted} ошибок старше 7 дней.")
