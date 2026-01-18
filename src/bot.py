"""Main bot entry point."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import config
from config import get_token
from dependencies import init_dependencies
from handlers import setup_routers
from tasks import periodic_chapter_check, stop_periodic_check
from middlewares import ThrottlingMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Main entry point."""
    # Initialize dependencies
    init_dependencies()
    
    # Setup bot
    token = get_token()
    bot = Bot(token)
    storage = MemoryStorage()
    dispatcher = Dispatcher(storage=storage)
    
    # Add anti-spam middleware
    dispatcher.message.middleware(ThrottlingMiddleware(rate_limit=0.5))
    dispatcher.callback_query.middleware(ThrottlingMiddleware(callback_limit=0.3))
    
    # Get bot username for deep links
    bot_info = await bot.get_me()
    config.BOT_USERNAME = bot_info.username
    logger.info(f"Bot username: @{config.BOT_USERNAME}")
    
    # Initialize Telethon for large file uploads (optional)
    from telethon_client import init_telethon, close_telethon, is_telethon_available
    if is_telethon_available():
        await init_telethon()
    else:
        logger.info("Telethon not configured (API_ID/API_HASH missing). Large files will be compressed.")
    
    # Include routers
    dispatcher.include_router(setup_routers())
    
    # Start background task for chapter notifications
    chapter_check_task = asyncio.create_task(periodic_chapter_check(bot, interval_seconds=3600))
    
    logger.info("Starting bot...")
    try:
        await dispatcher.start_polling(bot)
    finally:
        stop_periodic_check()
        chapter_check_task.cancel()
        try:
            await chapter_check_task
        except asyncio.CancelledError:
            pass
        # Close Telethon connection
        await close_telethon()


if __name__ == "__main__":
    asyncio.run(main())
