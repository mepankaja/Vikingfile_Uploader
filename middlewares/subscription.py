"""
Subscription gate middleware.

On first interaction, checks if the user is a member of REQUIRED_CHANNEL.
If not, blocks all actions and shows a "Subscribe to continue" prompt.
Once subscribed, the check is cached in memory for the session.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.types import (
    CallbackQuery, Chat, InlineKeyboardButton,
    InlineKeyboardMarkup, Message, TelegramObject,
)

logger = logging.getLogger(__name__)

REQUIRED_CHANNEL = "@NXT_HUB"

# In-memory cache of verified user IDs (resets on bot restart — cheap and fine)
_verified: set[int] = set()

_NOT_SUBSCRIBED_TEXT = (
    "👋 <b>Welcome to NXT Viking!</b>\n"
    "┌─────────────────────────\n"
    "│ To use this bot you must\n"
    "│ first join our channel:\n"
    "│\n"
    "│ 📢 <b>@NXT_HUB</b>\n"
    "└─────────────────────────\n"
    "\n"
    "After joining, tap <b>✅ I've Subscribed</b> below."
)

_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📢 Join @NXT_HUB", url="https://t.me/NXT_HUB")],
    [InlineKeyboardButton(text="✅ I've Subscribed", callback_data="check_sub")],
])


async def _is_member(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status not in ("left", "kicked", "banned")
    except (TelegramForbiddenError, TelegramBadRequest):
        # Bot not in channel or channel doesn't exist — fail open so bot still works
        logger.warning(
            f"Could not check membership for {REQUIRED_CHANNEL}. "
            "Make sure the bot is an admin of the channel."
        )
        return True
    except Exception as e:
        logger.warning(f"Subscription check error: {e}")
        return True


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Resolve user and bot from event
        if isinstance(event, Message):
            user = event.from_user
            bot: Bot = data["bot"]

            if not user:
                return await handler(event, data)

            uid = user.id

            # Already verified this session
            if uid in _verified:
                return await handler(event, data)

            if await _is_member(bot, uid):
                _verified.add(uid)
                return await handler(event, data)

            await event.answer(_NOT_SUBSCRIBED_TEXT, reply_markup=_KB)
            return

        elif isinstance(event, CallbackQuery):
            user = event.from_user
            bot: Bot = data["bot"]

            if not user:
                return await handler(event, data)

            uid = user.id

            # Let the "I've Subscribed" check-button through always
            if event.data == "check_sub":
                return await handler(event, data)

            if uid in _verified:
                return await handler(event, data)

            if await _is_member(bot, uid):
                _verified.add(uid)
                return await handler(event, data)

            await event.answer("❗ Please join @NXT_HUB first.", show_alert=True)
            return

        return await handler(event, data)
