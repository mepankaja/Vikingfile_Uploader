import asyncio
import os
import time
import re
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import TEMP_DIR, TG_BOT_MAX_SIZE
from keyboards.buttons import cancel_kb, main_menu_kb, back_to_menu_kb, setup_required_kb
from utils import db, formatting, viking_api
from utils.logger import log_upload
from utils.downloader import download_file
from utils.tg_downloader import download_tg_file
from utils import task_manager

router   = Router()
URL_RE   = re.compile(r"https?://[^\s]+")
PROG_INT = 2.0  # seconds between progress edits (Telegram rate limit safe)

_BAD_USER_SIGNALS = ("bad user", "invalid user", "user not found")


def _is_bad_user_error(msg: str) -> bool:
    low = msg.lower()
    return any(sig in low for sig in _BAD_USER_SIGNALS)


def _temp(filename: str, uid: int) -> str:
    path = os.path.join(TEMP_DIR, str(uid))
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, filename)


async def _safe_edit(msg: Message, text: str, markup=None):
    try:
        await msg.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        pass


# ── File upload task ───────────────────────────────────────────────────────────

async def _do_file_upload(message: Message, bot: Bot, doc, filename: str, file_size: int):
    user_id   = message.from_user.id
    user      = await db.async_get_user(user_id)
    user_hash = user.get("hash", "")
    user_path = user.get("default_path", "")
    task_key  = f"upload_{user_id}"
    icon      = formatting.get_file_icon(filename)

    # Warn upfront if hash is missing
    if not user_hash:
        await message.answer(
            formatting.setup_required_card(),
            reply_markup=setup_required_kb(),
            disable_web_page_preview=True,
        )
        task_manager.done(task_key)
        return

    status_msg = await message.answer(
        f"📥 <b>Received</b>\n"
        f"┌─────────────────────────\n"
        f"│ {icon} <b>{formatting._esc(filename[:36])}</b>\n"
        f"│ 📦 {formatting.format_size(file_size)}\n"
        f"└─────────────────────────\n"
        f"<i>Preparing…</i>",
        reply_markup=cancel_kb(f"cancel_upload_{user_id}")
    )

    local_path = _temp(filename, user_id)
    try:
        # ── Step 1: Download from Telegram ──────────────────────────────────
        last_upd = [0.0]

        async def dl_progress(done, total, speed, elapsed):
            now = time.time()
            if now - last_upd[0] < PROG_INT:
                return
            last_upd[0] = now
            await _safe_edit(
                status_msg,
                formatting.download_progress_card(filename, done, total, speed, elapsed),
                cancel_kb(f"cancel_upload_{user_id}")
            )

        await download_tg_file(bot, doc.file_id, file_size, local_path, dl_progress)

        # ── Step 2: Upload to VikingFile ─────────────────────────────────────
        actual_size = os.path.getsize(local_path)
        start_ul    = time.time()
        last_upd[0] = 0.0

        async def ul_progress(done, total):
            now = time.time()
            if now - last_upd[0] < PROG_INT:
                return
            last_upd[0] = now
            elapsed = time.time() - start_ul
            speed   = done / elapsed if elapsed > 0 else 0
            await _safe_edit(
                status_msg,
                formatting.upload_progress_card(filename, done, total, speed, elapsed),
                cancel_kb(f"cancel_upload_{user_id}")
            )

        result = await viking_api.upload_file_multipart(
            local_path, filename, user_hash, user_path, ul_progress
        )
        if user_path:
            await db.async_remember_path(user_id, user_path)

        res_name = result.get("name") or filename
        res_size = int(result.get("size") or actual_size)
        res_url  = result.get("_url") or ""
        res_hash = result.get("hash") or ""

        await _safe_edit(
            status_msg,
            formatting.success_card(res_name, res_size, res_url, res_hash, user_hash),
            None
        )
        await log_upload(
            bot, user_id, message.from_user.username, message.from_user.first_name,
            res_name, res_size, res_url, res_hash, user_hash,
        )

    except asyncio.CancelledError:
        await _safe_edit(status_msg, "⛔ <b>Upload cancelled.</b>", None)
    except RuntimeError as e:
        err = str(e)
        if _is_bad_user_error(err):
            await _safe_edit(status_msg, formatting.setup_required_card(), setup_required_kb())
        else:
            await _safe_edit(status_msg, formatting.error_card("Upload Failed", err), None)
    except Exception as e:
        await _safe_edit(status_msg, formatting.error_card("Upload Failed", str(e)[:300]), None)
    finally:
        task_manager.done(task_key)
        if user.get("auto_delete_temp", True) and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception:
                pass


# ── Link upload task ───────────────────────────────────────────────────────────

async def _do_link_upload(message: Message, url: str):
    user_id   = message.from_user.id
    user      = await db.async_get_user(user_id)
    user_hash = user.get("hash", "")
    user_path = user.get("default_path", "")
    task_key  = f"upload_{user_id}"
    display   = url[:46] + "…" if len(url) > 46 else url

    status_msg = await message.answer(
        f"🔗 <b>Remote Upload</b>\n"
        f"┌─────────────────────────\n"
        f"│ <code>{formatting._esc(display)}</code>\n"
        f"│\n"
        f"│ ⏳ VikingFile is fetching the\n"
        f"│    file on their servers…\n"
        f"│\n"
        f"│ ♾ No size limit — may take\n"
        f"│    a few minutes for large files\n"
        f"└─────────────────────────",
        reply_markup=cancel_kb(f"cancel_upload_{user_id}"),
        disable_web_page_preview=True,
    )

    try:
        last_upd  = [0.0]
        start_rl  = time.time()

        async def remote_progress(current, total, pct_str, fname):
            now = time.time()
            if now - last_upd[0] < PROG_INT:
                return
            last_upd[0] = now
            elapsed = now - start_rl
            speed   = current / elapsed if elapsed > 0 else 0
            name_show = fname if fname else display
            await _safe_edit(
                status_msg,
                formatting.remote_progress_card(name_show, current, total, speed, pct_str),
                cancel_kb(f"cancel_upload_{user_id}"),
            )

        result   = await viking_api.upload_remote_link(url, user_hash, path=user_path, progress_cb=remote_progress)
        if user_path:
            await db.async_remember_path(user_id, user_path)
        res_name = result.get("name") or url.split("/")[-1] or "file"
        res_size = int(result.get("size") or 0)
        res_url  = result.get("_url") or result.get("url") or ""
        res_hash = result.get("hash") or ""
        await _safe_edit(
            status_msg,
            formatting.success_card(res_name, res_size, res_url, res_hash, user_hash),
            None
        )
        await log_upload(
            message.bot, user_id, message.from_user.username, message.from_user.first_name,
            res_name, res_size, res_url, res_hash, user_hash,
        )
    except asyncio.CancelledError:
        await _safe_edit(status_msg, "⛔ <b>Upload cancelled.</b>", None)
    except RuntimeError as e:
        err = str(e)
        if _is_bad_user_error(err):
            await _safe_edit(status_msg, formatting.setup_required_card(), setup_required_kb())
        else:
            await _safe_edit(status_msg, formatting.error_card("Remote Upload Failed", err[:300]), None)
    except Exception as e:
        await _safe_edit(status_msg, formatting.error_card("Remote Upload Failed", str(e)[:300]), None)
    finally:
        task_manager.done(task_key)


# ── Public wrappers (register cancellable tasks) ───────────────────────────────

async def handle_file_upload(message: Message, bot: Bot):
    doc = message.document or message.video or message.audio
    if not doc and message.photo:
        doc = message.photo[-1]
    if not doc:
        return

    filename  = getattr(doc, "file_name", None) or f"file_{doc.file_unique_id}"
    file_size = int(getattr(doc, "file_size", 0) or 0)
    user_id   = message.from_user.id

    task_manager.cancel_all_for_user(user_id)
    task = asyncio.create_task(_do_file_upload(message, bot, doc, filename, file_size))
    task_manager.register(f"upload_{user_id}", task)


async def handle_link_upload(message: Message, url: str):
    user_id = message.from_user.id
    task_manager.cancel_all_for_user(user_id)
    task = asyncio.create_task(_do_link_upload(message, url))
    task_manager.register(f"upload_{user_id}", task)


# ── Commands ───────────────────────────────────────────────────────────────────

@router.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext):
    user_id = msg.from_user.id
    task_manager.cancel_all_for_user(user_id)
    current = await state.get_state()
    await state.clear()
    await msg.answer(
        "⛔ <b>Operation cancelled.</b>" if current else "ℹ️ Nothing to cancel.",
        reply_markup=None
    )


# ── Message routing ────────────────────────────────────────────────────────────

@router.message(F.document | F.video | F.audio | F.photo)
async def on_file(msg: Message, bot: Bot, state: FSMContext):
    from handlers.zip_handler import ZipStates, add_file_to_zip
    current = await state.get_state()
    if current == ZipStates.collecting:
        await add_file_to_zip(msg, bot, state)
        return
    if current is None:
        await handle_file_upload(msg, bot)


ZIP_BUTTONS = {"✅ Done", "❌ Cancel ZIP", "⏭ Skip Password"}

@router.message(F.text & ~F.text.startswith("/"))
async def on_text(msg: Message, bot: Bot, state: FSMContext):
    from handlers.zip_handler import ZipStates, add_link_to_zip
    current = await state.get_state()
    if current == ZipStates.collecting:
        if URL_RE.match(msg.text.strip()):
            await add_link_to_zip(msg, state)
        else:
            await msg.answer("⚠️ Please send a valid URL or a file.")
        return
    if current is not None:
        return
    text = msg.text.strip()
    if text in ZIP_BUTTONS or text.startswith("✅ Keep:"):
        return  # handled by zip_handler
    if URL_RE.match(text):
        await handle_link_upload(msg, text)
    else:
        await msg.answer(
            "💡 <b>What I can do:</b>\n"
            "┌─────────────────────────\n"
            "│ 📎 Send a <b>file</b> → upload it\n"
            "│ 🔗 Paste a <b>URL</b> → remote fetch\n"
            "│ 🗜 Tap <b>ZIP</b> → bundle files\n"
            "│ 📖 /help → full guide\n"
            "└─────────────────────────",
            reply_markup=None
        )


# ── Cancel callbacks ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cancel_upload_"))
async def cb_cancel_upload(cb: CallbackQuery, state: FSMContext):
    user_id     = cb.from_user.id
    was_running = task_manager.cancel(f"upload_{user_id}")
    await cb.message.edit_text(
        "⛔ Upload cancelled." if was_running else "ℹ️ No active upload.",
        reply_markup=None
    )
    await cb.answer("Cancelled" if was_running else "Nothing to cancel")
