"""
Log channel utility — sends upload events to LOG_CHANNEL_ID silently.
Errors are swallowed so logging never breaks the main flow.
"""
import logging
from typing import Optional
from aiogram import Bot
from config import LOG_CHANNEL_ID, NXT_HUB_USERNAME, NXT_HUB_LINK
from utils.formatting import format_size, _esc

log = logging.getLogger(__name__)


def _is_configured() -> bool:
    return bool(LOG_CHANNEL_ID)


async def log_upload(
    bot: Bot,
    user_id: int,
    username: Optional[str],
    first_name: str,
    filename: str,
    size: int,
    url: str,
    file_hash: str,
    user_hash: str = "",
    zip_file: bool = False,
    file_count: int = 0,
) -> None:
    """Send an upload log entry to the log channel."""
    if not _is_configured():
        return
    try:
        uname    = f"@{username}" if username else f"<a href='tg://user?id={user_id}'>{_esc(first_name)}</a>"
        kind     = "🗜 ZIP" if zip_file else "📤 Upload"
        account  = "👤 Account" if user_hash else "🔓 Anonymous"
        fc_line  = f"\n│ 📂 Files: {file_count}" if zip_file else ""
        url_line = f"\n│ 🔗 <a href='{url}'>{_esc(filename[:40])}</a>" if url else ""

        text = (
            f"{kind} · {account}\n"
            f"┌─────────────────────────\n"
            f"│ 👤 {uname}  (<code>{user_id}</code>)\n"
            f"│ 📄 <b>{_esc(filename[:48])}</b>\n"
            f"│ 📦 {format_size(size)}"
            f"{fc_line}"
            f"{url_line}\n"
            f"└─────────────────────────\n"
            f"<a href='{NXT_HUB_LINK}'>{NXT_HUB_USERNAME}</a>"
        )
        await bot.send_message(
            LOG_CHANNEL_ID, text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.debug(f"Log channel send failed: {e}")
