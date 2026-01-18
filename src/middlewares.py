"""Middlewares for the bot."""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject


class ThrottlingMiddleware(BaseMiddleware):
    """
    Advanced anti-spam middleware with:
    - Rate limiting (min interval between requests)
    - Request counting (max requests per minute)
    - Warning system with temporary bans
    - Separate limits for messages and callbacks
    """
    
    def __init__(
        self, 
        rate_limit: float = 0.5,           # Min seconds between messages
        callback_limit: float = 0.3,        # Min seconds between callbacks
        max_requests_per_minute: int = 30,  # Max requests per minute
        warn_threshold: int = 3,            # Warnings before temp ban
        ban_duration: int = 60,             # Temp ban duration in seconds
    ) -> None:
        self.rate_limit = rate_limit
        self.callback_limit = callback_limit
        self.max_requests_per_minute = max_requests_per_minute
        self.warn_threshold = warn_threshold
        self.ban_duration = ban_duration
        
        # Tracking dictionaries
        self.user_last_message: Dict[int, float] = {}
        self.user_last_callback: Dict[int, float] = {}
        self.user_requests: Dict[int, list] = defaultdict(list)  # timestamps of requests
        self.user_warnings: Dict[int, int] = defaultdict(int)
        self.user_banned_until: Dict[int, float] = {}
        
        super().__init__()
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id = None
        
        # Get user ID
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None
        
        if user_id is None:
            return await handler(event, data)
        
        current_time = time.time()
        
        # Check if user is banned
        if user_id in self.user_banned_until:
            if current_time < self.user_banned_until[user_id]:
                remaining = int(self.user_banned_until[user_id] - current_time)
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer(f"🚫 Подожди {remaining} сек.", show_alert=True)
                    except Exception:
                        pass
                elif isinstance(event, Message):
                    try:
                        await event.answer(f"🚫 Слишком много запросов! Подожди {remaining} секунд.")
                    except Exception:
                        pass
                return None
            else:
                # Ban expired
                del self.user_banned_until[user_id]
                self.user_warnings[user_id] = 0
        
        # Check rate limit (min interval)
        if isinstance(event, Message):
            last_time = self.user_last_message.get(user_id, 0)
            limit = self.rate_limit
        else:
            last_time = self.user_last_callback.get(user_id, 0)
            limit = self.callback_limit
        
        # Too fast?
        if current_time - last_time < limit:
            self.user_warnings[user_id] += 1
            
            if self.user_warnings[user_id] >= self.warn_threshold:
                # Temporary ban
                self.user_banned_until[user_id] = current_time + self.ban_duration
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer(f"🚫 Слишком быстро! Бан на {self.ban_duration} сек.", show_alert=True)
                    except Exception:
                        pass
                elif isinstance(event, Message):
                    try:
                        await event.answer(f"🚫 Слишком много запросов! Подожди {self.ban_duration} секунд.")
                    except Exception:
                        pass
                return None
            
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("⏳ Помедленнее...", show_alert=False)
                except Exception:
                    pass
            return None
        
        # Check requests per minute
        minute_ago = current_time - 60
        self.user_requests[user_id] = [t for t in self.user_requests[user_id] if t > minute_ago]
        
        if len(self.user_requests[user_id]) >= self.max_requests_per_minute:
            self.user_warnings[user_id] += 1
            
            if self.user_warnings[user_id] >= self.warn_threshold:
                self.user_banned_until[user_id] = current_time + self.ban_duration
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer(f"🚫 Лимит запросов! Бан на {self.ban_duration} сек.", show_alert=True)
                    except Exception:
                        pass
                elif isinstance(event, Message):
                    try:
                        await event.answer(f"🚫 Превышен лимит запросов! Подожди {self.ban_duration} секунд.")
                    except Exception:
                        pass
                return None
            
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("⏳ Слишком много запросов в минуту", show_alert=False)
                except Exception:
                    pass
            return None
        
        # Record this request
        self.user_requests[user_id].append(current_time)
        
        # Update last action time
        if isinstance(event, Message):
            self.user_last_message[user_id] = current_time
        else:
            self.user_last_callback[user_id] = current_time
        
        # Decay warnings over time (if user behaves)
        if self.user_warnings[user_id] > 0 and len(self.user_requests[user_id]) < 10:
            self.user_warnings[user_id] = max(0, self.user_warnings[user_id] - 1)
        
        # Periodic cleanup (every ~1000 users)
        if len(self.user_requests) > 1000:
            self._cleanup(current_time)
        
        return await handler(event, data)
    
    def _cleanup(self, current_time: float) -> None:
        """Remove old entries to prevent memory leaks."""
        cutoff = current_time - 120  # 2 minutes
        
        # Clean request history
        to_remove = [uid for uid, times in self.user_requests.items() 
                     if not times or max(times) < cutoff]
        for uid in to_remove:
            del self.user_requests[uid]
        
        # Clean last message/callback times
        for d in [self.user_last_message, self.user_last_callback]:
            to_remove = [uid for uid, t in d.items() if t < cutoff]
            for uid in to_remove:
                del d[uid]
        
        # Clean expired bans
        to_remove = [uid for uid, t in self.user_banned_until.items() if t < current_time]
        for uid in to_remove:
            del self.user_banned_until[uid]
            self.user_warnings.pop(uid, None)
