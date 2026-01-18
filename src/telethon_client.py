"""Telethon client for sending large files (up to 2GB).

Telethon uses MTProto directly, bypassing Bot API's 50MB limit.
Used only for sending large volume files when aiogram fails.
"""
from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Callable, Awaitable

from telethon import TelegramClient
from telethon.sessions import StringSession

import config

if TYPE_CHECKING:
    from telethon.types import Message

logger = logging.getLogger(__name__)

# Type for message progress callback
MessageProgressCallback = Callable[[int, int, str], Awaitable[None]]

# Global Telethon client instance
_telethon_client: TelegramClient | None = None
_initialized = False


async def init_telethon() -> TelegramClient | None:
    """Initialize Telethon client with bot token.
    
    Returns:
        TelegramClient if successfully initialized, None otherwise.
    """
    global _telethon_client, _initialized
    
    if _initialized:
        return _telethon_client
    
    _initialized = True
    
    if not config.API_ID or not config.API_HASH:
        logger.warning(
            "Telethon not configured: API_ID and API_HASH required. "
            "Get them from https://my.telegram.org"
        )
        return None
    
    if not config.TELEGRAM_TOKEN:
        logger.warning("Telethon: TELEGRAM_TOKEN required")
        return None
    
    try:
        # Use StringSession for stateless operation (no session file needed)
        _telethon_client = TelegramClient(
            StringSession(),
            config.API_ID,
            config.API_HASH,
        )
        
        # Start client with bot token
        await _telethon_client.start(bot_token=config.TELEGRAM_TOKEN)
        
        me = await _telethon_client.get_me()
        logger.info(f"Telethon initialized: @{me.username}")
        
        return _telethon_client
        
    except Exception as e:
        logger.error(f"Failed to initialize Telethon: {e}")
        _telethon_client = None
        return None


async def get_telethon() -> TelegramClient | None:
    """Get initialized Telethon client."""
    global _telethon_client
    
    if _telethon_client is None:
        return await init_telethon()
    
    return _telethon_client


async def close_telethon() -> None:
    """Close Telethon client connection."""
    global _telethon_client, _initialized
    
    if _telethon_client:
        await _telethon_client.disconnect()
        _telethon_client = None
    
    _initialized = False


async def send_large_file(
    chat_id: int,
    file_path: str,
    caption: str | None = None,
    filename: str | None = None,
    progress_callback=None,
    message_callback: MessageProgressCallback | None = None,
) -> tuple[Message | None, str | None]:
    """Send large file using Telethon (up to 2GB).
    
    Args:
        chat_id: Telegram chat ID to send to
        file_path: Path to the file to send
        caption: Optional caption for the file
        filename: Optional filename override
        progress_callback: Optional callback(current, total) for raw progress
        message_callback: Optional async callback(current, total, text) for message updates
        
    Returns:
        Tuple of (Telethon Message object, file_id string) if successful, (None, None) otherwise.
        The file_id can be used with aiogram to send the file again without re-uploading.
    """
    from telethon.utils import pack_bot_file_id
    
    client = await get_telethon()
    
    if not client:
        logger.error("Telethon client not available for large file upload")
        return None, None
    
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return None, None
    
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    file_size = os.path.getsize(file_path)
    logger.info(f"Sending large file via Telethon: {file_size_mb:.1f} MB to chat {chat_id}")
    
    # Create progress wrapper to update message
    last_update_time = [0.0]
    
    async def upload_progress(current: int, total: int):
        """Progress callback that updates message."""
        now = time.time()
        # Update every 3 seconds max
        if now - last_update_time[0] < 3.0:
            return
        last_update_time[0] = now
        
        percent = int((current / total) * 100)
        current_mb = current / (1024 * 1024)
        total_mb = total / (1024 * 1024)
        
        logger.info(f"[Telethon Upload] {percent}% ({current_mb:.1f}/{total_mb:.1f} MB)")
        
        if message_callback:
            try:
                await message_callback(
                    current, total, 
                    f"📤 Загрузка: {percent}% ({current_mb:.1f}/{total_mb:.1f} MB)"
                )
            except Exception:
                pass
    
    try:
        # Send file with Telethon
        # force_document=True ensures it's sent as document, not media
        message = await client.send_file(
            chat_id,
            file_path,
            caption=caption,
            force_document=True,
            progress_callback=upload_progress if message_callback else progress_callback,
            attributes=[],  # Let Telethon determine attributes
        )
        
        # Extract file_id compatible with Bot API / aiogram
        file_id = None
        if message and message.document:
            try:
                file_id = pack_bot_file_id(message.document)
                logger.info(f"Extracted file_id: {file_id[:20]}...")
            except Exception as e:
                logger.warning(f"Could not extract file_id: {e}")
        
        logger.info(f"Successfully sent large file to chat {chat_id}")
        return message, file_id
        
    except Exception as e:
        logger.error(f"Failed to send large file via Telethon: {e}")
        return None, None


def is_telethon_available() -> bool:
    """Check if Telethon is configured and available."""
    return bool(config.API_ID and config.API_HASH and config.TELEGRAM_TOKEN)
