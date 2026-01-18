"""Background tasks for the bot."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiogram import Bot

from dependencies import get_client, get_favorites
from utils import run_sync

if TYPE_CHECKING:
    from favorites import FavoritesStore
    from desu_client import DesuClient

logger = logging.getLogger(__name__)

# Global flag to control task
_check_task_running = False


async def check_new_chapters(bot: Bot) -> None:
    """Check all favorite manga for new chapters and send notifications."""
    store = get_favorites()
    client = get_client()
    
    # Get all unique manga from favorites
    manga_data = {}  # manga_id -> (title, [user_ids])
    for manga_id, user_id, title in store.get_all_favorite_manga_ids():
        if manga_id not in manga_data:
            manga_data[manga_id] = {"title": title, "users": []}
        manga_data[manga_id]["users"].append(user_id)
    
    logger.info(f"Checking {len(manga_data)} manga for new chapters...")
    
    for manga_id, data in manga_data.items():
        try:
            # Get current chapter count from API
            chapters = await run_sync(client.get_manga_chapters, manga_id)
            current_count = len(chapters) if chapters else 0
            
            # Get last known count
            last_count = store.get_manga_chapter_count(manga_id)
            
            if last_count is None:
                # First time checking this manga, just save count
                store.set_manga_chapter_count(manga_id, current_count)
                continue
            
            if current_count > last_count:
                # New chapters detected!
                new_chapters = current_count - last_count
                store.set_manga_chapter_count(manga_id, current_count)
                
                # Get latest chapter info
                latest_chapter = chapters[0] if chapters else None
                ch_info = ""
                if latest_chapter:
                    ch_num = latest_chapter.get("ch") or latest_chapter.get("vol") or ""
                    ch_info = f"\n📖 Последняя: Глава {ch_num}" if ch_num else ""
                
                # Notify all users who have this manga in favorites
                message = (
                    f"🔔 <b>Новые главы!</b>\n\n"
                    f"📚 <b>{data['title']}</b>\n"
                    f"➕ Добавлено глав: {new_chapters}{ch_info}"
                )
                
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📖 Открыть", callback_data=f"manga:{manga_id}")]
                ])
                
                for user_id in data["users"]:
                    # Check if user has notifications enabled
                    if not store.is_notifications_enabled(user_id):
                        continue
                    
                    try:
                        await bot.send_message(
                            user_id,
                            message,
                            reply_markup=keyboard,
                            parse_mode="HTML"
                        )
                        logger.info(f"Sent notification to {user_id} about {data['title']}")
                    except Exception as e:
                        logger.warning(f"Failed to notify user {user_id}: {e}")
                        store.log_error("notification", str(e), f"user_id={user_id}, manga_id={manga_id}")
            
            # Small delay to avoid API rate limits
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Error checking manga {manga_id}: {e}")
            store.log_error("chapter_check", str(e), f"manga_id={manga_id}")


async def periodic_chapter_check(bot: Bot, interval_seconds: int = 3600) -> None:
    """Run chapter check periodically (default: every hour)."""
    global _check_task_running
    _check_task_running = True
    
    logger.info(f"Starting periodic chapter check (interval: {interval_seconds}s)")
    
    while _check_task_running:
        try:
            await check_new_chapters(bot)
        except Exception as e:
            logger.error(f"Error in periodic check: {e}")
            store = get_favorites()
            store.log_error("periodic_check", str(e))
        
        await asyncio.sleep(interval_seconds)


def stop_periodic_check() -> None:
    """Stop the periodic check task."""
    global _check_task_running
    _check_task_running = False
