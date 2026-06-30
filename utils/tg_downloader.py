"""
Telegram file downloader — one shared Pyrogram client, no SQLite.

Routing:
  ≤ 20 MB  → Bot API  (simple HTTP)
  > 20 MB  → Pyrogram MTProto  (shared client, MemoryStorage — no .session file)

Key design:
  - Single persistent Pyrogram client started at bot startup
  - MemoryStorage: session kept in RAM, zero SQLite files written
  - No semaphore here — callers control concurrency (zip_handler uses its own)
  - Bot API downloads use multi-threaded HTTP downloader for speed
"""
import asyncio
import logging
import os
import time
from typing import Optional, Callable

from aiogram import Bot
from config import (
    PYROGRAM_API_ID, PYROGRAM_API_HASH, BOT_TOKEN,
    TEMP_DIR, TG_BOT_MAX_SIZE,
)
from utils.downloader import download_file

logger = logging.getLogger(__name__)

_pyro_client = None
_pyro_lock   = asyncio.Lock()


async def get_pyro_client():
    """Return the shared Pyrogram client, starting it if needed (MemoryStorage)."""
    global _pyro_client

    if _pyro_client is not None and _pyro_client.is_connected:
        return _pyro_client

    async with _pyro_lock:
        if _pyro_client is not None and _pyro_client.is_connected:
            return _pyro_client

        try:
            from pyrogram import Client
            from pyrogram.storage import MemoryStorage
        except ImportError:
            raise RuntimeError(
                "pyrogram not installed. Add 'pyrogram' and 'TgCrypto' to requirements.txt."
            )

        client = Client(
            name="nxtup_bot",
            api_id=PYROGRAM_API_ID,
            api_hash=PYROGRAM_API_HASH,
            bot_token=BOT_TOKEN,
            storage=MemoryStorage("nxtup_bot"),  # RAM only — no .session SQLite file
            no_updates=True,
        )
        await client.start()
        _pyro_client = client
        logger.info("✅ Pyrogram client started (MemoryStorage — no SQLite)")
        return client


async def stop_pyro_client():
    """Gracefully stop the shared Pyrogram client."""
    global _pyro_client
    if _pyro_client and _pyro_client.is_connected:
        await _pyro_client.stop()
        _pyro_client = None
        logger.info("Pyrogram client stopped")


# ── Main entry point ───────────────────────────────────────────────────────────

async def download_tg_file(
    bot: Bot,
    file_id: str,
    file_size: int,
    dest_path: str,
    progress_cb: Optional[Callable] = None,
) -> str:
    """
    Download a Telegram file to dest_path.
    progress_cb: async (done, total, speed, elapsed)
    """
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)

    if file_size <= TG_BOT_MAX_SIZE or file_size == 0:
        await _bot_api_download(bot, file_id, file_size, dest_path, progress_cb)
    else:
        await _pyrogram_download(file_id, file_size, dest_path, progress_cb)

    return dest_path


async def _bot_api_download(
    bot: Bot,
    file_id: str,
    file_size: int,
    dest_path: str,
    progress_cb: Optional[Callable],
):
    file_info   = await bot.get_file(file_id)
    url         = f"https://api.telegram.org/file/bot{bot.token}/{file_info.file_path}"
    known_total = int(file_info.file_size or 0) or file_size

    if progress_cb and known_total:
        async def _cb(done, total, speed, elapsed):
            await progress_cb(done, known_total, speed, elapsed)
        await download_file(url, dest_path, _cb)
    else:
        await download_file(url, dest_path, progress_cb)


async def _pyrogram_download(
    file_id: str,
    file_size: int,
    dest_path: str,
    progress_cb: Optional[Callable],
):
    if not PYROGRAM_API_ID or not PYROGRAM_API_HASH:
        raise RuntimeError(
            "File > 20 MB requires Pyrogram. Set PYROGRAM_API_ID and "
            "PYROGRAM_API_HASH in config.py (get them at https://my.telegram.org)."
        )

    start    = time.time()
    last_upd = [0.0]

    async def _pyro_progress(current: int, total: int):
        if not progress_cb:
            return
        now = time.time()
        if now - last_upd[0] < 0.5:
            return
        last_upd[0] = now
        elapsed = now - start
        speed   = current / elapsed if elapsed > 0 else 0
        await progress_cb(current, total or file_size, speed, elapsed)

    # No semaphore here — zip_handler.MAX_CONCURRENT_DL controls concurrency
    client = await get_pyro_client()
    await client.download_media(
        file_id,
        file_name=dest_path,
        progress=_pyro_progress,
    )
