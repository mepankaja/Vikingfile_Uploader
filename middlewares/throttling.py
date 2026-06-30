import asyncio
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
from typing import Any, Awaitable, Callable, Dict
import time

_last_message: Dict[int, float] = {}
THROTTLE_RATE = 0.5  # seconds between messages


class ThrottlingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            uid = event.from_user.id if event.from_user else 0
            now = time.time()
            last = _last_message.get(uid, 0)
            if now - last < THROTTLE_RATE:
                return
            _last_message[uid] = now
        return await handler(event, data)
