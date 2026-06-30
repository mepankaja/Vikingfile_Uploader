"""
Hidden admin broadcast feature.

Not registered with BotFather (intentionally absent from /start commands list)
so regular users never see or discover it. Only responds to user IDs in
config.ADMIN_IDS — everyone else gets silently ignored (no error, no hint
that this command exists).

Usage (admin only):
  /broadcast <message>          → text broadcast to all known users
  Reply to any message with /broadcast → forwards/copies that message to all users
"""
import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.filters import Command

from config import ADMIN_IDS
from utils import db

logger = logging.getLogger(__name__)
router  = Router()

_BROADCAST_DELAY = 0.05   # seconds between sends — avoid Telegram flood limits


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@router.message(Command("broadcast"))
async def cmd_broadcast(msg: Message, bot: Bot):
    # Silently ignore non-admins — no error message, command stays invisible
    if not _is_admin(msg.from_user.id):
        return

    text = msg.text.partition(" ")[2].strip() if msg.text else ""
    reply = msg.reply_to_message

    if not text and not reply:
        await msg.answer(
            "📢 <b>Broadcast</b>\n"
            "┌─────────────────────────\n"
            "│ Usage:\n"
            "│ <code>/broadcast your message</code>\n"
            "│\n"
            "│ Or reply to any message with\n"
            "│ <code>/broadcast</code> to forward it.\n"
            "└─────────────────────────"
        )
        return

    user_ids = await db.async_get_all_user_ids()
    total    = len(user_ids)
    if total == 0:
        await msg.answer("⚠️ No users found in database.")
        return

    status = await msg.answer(
        f"📢 <b>Broadcasting…</b>\n"
        f"┌─────────────────────────\n"
        f"│ 🎯 Target: {total} users\n"
        f"│ ✅ Sent: 0\n"
        f"│ ❌ Failed: 0\n"
        f"└─────────────────────────"
    )

    sent, failed = 0, 0
    for i, uid in enumerate(user_ids):
        try:
            if reply:
                await bot.copy_message(uid, msg.chat.id, reply.message_id)
            else:
                await bot.send_message(uid, text, disable_web_page_preview=True)
            sent += 1
        except Exception as e:
            failed += 1
            logger.debug(f"Broadcast failed for {uid}: {e}")

        # Update status every 25 sends to avoid rate-limiting the edit itself
        if (i + 1) % 25 == 0 or (i + 1) == total:
            try:
                await status.edit_text(
                    f"📢 <b>Broadcasting…</b>\n"
                    f"┌─────────────────────────\n"
                    f"│ 🎯 Target: {total} users\n"
                    f"│ ✅ Sent: {sent}\n"
                    f"│ ❌ Failed: {failed}\n"
                    f"└─────────────────────────"
                )
            except Exception:
                pass

        await asyncio.sleep(_BROADCAST_DELAY)

    await status.edit_text(
        f"✅ <b>Broadcast Complete</b>\n"
        f"┌─────────────────────────\n"
        f"│ 🎯 Target: {total} users\n"
        f"│ ✅ Sent: {sent}\n"
        f"│ ❌ Failed: {failed}\n"
        f"└─────────────────────────"
    )


@router.message(Command("stats"))
async def cmd_stats(msg: Message):
    """Hidden admin-only stats command."""
    if not _is_admin(msg.from_user.id):
        return
    user_ids = await db.async_get_all_user_ids()
    await msg.answer(
        f"📊 <b>Bot Stats</b>\n"
        f"┌─────────────────────────\n"
        f"│ 👥 Total Users: {len(user_ids)}\n"
        f"└─────────────────────────"
    )
