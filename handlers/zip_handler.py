import asyncio
import os
import re
import time
import zipfile
import shutil
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import TEMP_DIR
from keyboards.buttons import (
    cancel_kb, zip_collection_kb, zip_password_kb, zip_rename_kb, main_menu_kb
)
from utils import db, formatting, viking_api, downloader
from utils.logger import log_upload
from utils.tg_downloader import download_tg_file
from utils import task_manager

router = Router()
URL_RE = re.compile(r"https?://[^\s]+")

# Max concurrent downloads inside a ZIP build
MAX_CONCURRENT_DL = 8  # Pyrogram has no inner semaphore now — safe to go higher



def _zip_reply_kb() -> ReplyKeyboardMarkup:
    """Collection phase: Done + Cancel."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Done"), KeyboardButton(text="❌ Cancel ZIP")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Send files or URLs to add to ZIP…",
    )


def _zip_password_reply_kb() -> ReplyKeyboardMarkup:
    """Password phase: Skip + Cancel visible, input field for password."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ Skip Password"), KeyboardButton(text="❌ Cancel ZIP")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Type a password or tap Skip…",
    )


def _zip_rename_reply_kb(default_name: str) -> ReplyKeyboardMarkup:
    """Rename phase: keep-default button + cancel, input for custom name."""
    short = default_name if len(default_name) <= 26 else default_name[:23] + "…"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"✅ Keep: {short}")],
            [KeyboardButton(text="❌ Cancel ZIP")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Type a name or tap Keep Default…",
    )


class ZipStates(StatesGroup):
    collecting       = State()
    waiting_password = State()
    waiting_name     = State()
    building         = State()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _zip_temp_dir(uid: int) -> str:
    path = os.path.join(TEMP_DIR, f"zip_{uid}")
    os.makedirs(path, exist_ok=True)
    return path


async def _safe_edit(msg: Message, text: str, markup=None):
    try:
        await msg.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        pass


def _item_summary(items: list) -> str:
    if not items:
        return "│ <i>No items yet — send a file or URL.</i>"
    show  = items[-6:]
    lines = []
    if len(items) > 6:
        lines.append(f"│ … and {len(items)-6} more above")
    for item in show:
        if item["type"] == "link":
            icon     = "🔗"
            name     = item.get("name") or item.get("url", "?")
            size_tag = ""
        else:
            icon = formatting.get_file_icon(item.get("name", ""))
            name = item.get("name", "?")
            sz   = item.get("size", 0)
            size_tag = f"  <i>({formatting.format_size(sz)})</i>" if sz else ""
        lines.append(f"│ {icon} {formatting._esc(name[:30])}{size_tag}")
    return "\n".join(lines)


def _collection_stats(items: list):
    """Return (file_count, link_count, known_total_size, has_unknown_size)."""
    file_count  = sum(1 for i in items if i["type"] == "tg_file")
    link_count  = sum(1 for i in items if i["type"] == "link")
    known_size  = sum(i.get("size", 0) for i in items if i["type"] == "tg_file")
    has_unknown = link_count > 0  # remote link sizes unknown until fetched
    return file_count, link_count, known_size, has_unknown


def _collection_card(items: list) -> str:
    count = len(items)
    file_count, link_count, known_size, has_unknown = _collection_stats(items)

    if count == 0:
        size_line = "│ 📦 Estimated size: —\n"
    elif has_unknown:
        size_line = f"│ 📦 Estimated size: ~{formatting.format_size(known_size)}+  <i>(some unknown)</i>\n"
    else:
        size_line = f"│ 📦 Estimated size: ~{formatting.format_size(known_size)}\n"

    type_line = ""
    if file_count and link_count:
        type_line = f"│ 📎 {file_count} file{'s' if file_count != 1 else ''}  ·  🔗 {link_count} link{'s' if link_count != 1 else ''}\n"
    elif file_count:
        type_line = f"│ 📎 {file_count} file{'s' if file_count != 1 else ''}\n"
    elif link_count:
        type_line = f"│ 🔗 {link_count} link{'s' if link_count != 1 else ''}\n"

    return (
        f"🗜 <b>ZIP Builder · Collecting</b>\n"
        f"┌─────────────────────────\n"
        f"│ 🗂 <b>{count} item{'s' if count != 1 else ''}</b> added\n"
        f"{type_line}"
        f"{size_line}"
        f"│\n"
        f"{_item_summary(items)}\n"
        f"└─────────────────────────\n"
        f"<i>Send more files/URLs, or tap ✅ Done.</i>"
    )


def _default_zip_name() -> str:
    return f"archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"


def _unique_dest(files_dir: str, fname: str) -> str:
    """Ensure unique filename to avoid collisions in zip folder."""
    base, ext = os.path.splitext(fname)
    dest      = os.path.join(files_dir, fname)
    counter   = 1
    while os.path.exists(dest):
        dest = os.path.join(files_dir, f"{base}_{counter}{ext}")
        counter += 1
    return dest


def _make_zip(zip_path: str, files: list, level: int) -> None:
    """Create a standard (no-password) zip archive."""
    level = max(0, min(9, level))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
        for p in files:
            if os.path.exists(p):
                zf.write(p, os.path.basename(p))


def _make_zip_password(zip_path: str, files: list, level: int, password: str) -> bool:
    """
    Try to create a password-protected ZIP via pyminizip.
    Returns True on success, False if pyminizip is unavailable or fails.
    """
    try:
        import pyminizip
        srcs     = [os.path.abspath(str(p)) for p in files if os.path.exists(p)]
        prefixes = [""] * len(srcs)
        pzip_lvl = max(1, min(9, level))
        pyminizip.compress_multiple(srcs, prefixes, zip_path, password, pzip_lvl)
        return True
    except ImportError:
        return False
    except Exception:
        return False


# ── /zip command ───────────────────────────────────────────────────────────────

@router.message(Command("zip"))
async def cmd_zip(msg: Message, state: FSMContext):
    await state.clear()
    await state.set_state(ZipStates.collecting)
    sent = await msg.answer(
        "🗜 <b>ZIP Builder</b>\n"
        "┌─────────────────────────\n"
        "│ Send files &amp; URLs to add them.\n"
        "│ Tap ✅ <b>Done</b> or send /done when ready.\n"
        "└─────────────────────────"
    )
    await msg.answer("📎 Send files or paste URLs:", reply_markup=_zip_reply_kb())
    await state.update_data(items=[], status_msg_id=sent.message_id, chat_id=msg.chat.id)


@router.callback_query(F.data == "menu_zip")
async def cb_menu_zip(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(ZipStates.collecting)
    await cb.message.edit_text(
        "🗜 <b>ZIP Builder</b>\n"
        "┌─────────────────────────\n"
        "│ Send files &amp; URLs to add them.\n"
        "│ Tap ✅ <b>Done</b> or send /done when ready.\n"
        "└─────────────────────────"
    )
    await state.update_data(
        items=[], status_msg_id=cb.message.message_id, chat_id=cb.message.chat.id
    )
    await cb.answer()
    await cb.message.answer("📎 Send files or paste URLs:", reply_markup=_zip_reply_kb())


# ── Collecting: add files & links ──────────────────────────────────────────────

async def add_file_to_zip(msg: Message, bot: Bot, state: FSMContext):
    data  = await state.get_data()
    items = data.get("items", [])

    doc = msg.document or msg.video or msg.audio
    if not doc and msg.photo:
        doc = msg.photo[-1]
    if not doc:
        return

    filename  = getattr(doc, "file_name", None) or f"file_{doc.file_unique_id}"
    file_size = int(getattr(doc, "file_size", 0) or 0)

    items.append({
        "type":    "tg_file",
        "file_id": doc.file_id,
        "name":    filename,
        "size":    file_size,
    })
    await state.update_data(items=items)

    status_msg_id = data.get("status_msg_id")
    chat_id       = data.get("chat_id") or msg.chat.id
    if status_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id,
                text=_collection_card(items)
            )
        except Exception:
            pass
    # Keep the user's file message — don't delete it

async def add_link_to_zip(msg: Message, state: FSMContext):
    data  = await state.get_data()
    items = data.get("items", [])
    url   = msg.text.strip()
    name  = downloader.get_filename_from_url(url)

    items.append({"type": "link", "url": url, "name": name})
    await state.update_data(items=items)

    status_msg_id = data.get("status_msg_id")
    chat_id       = data.get("chat_id") or msg.chat.id
    if status_msg_id:
        try:
            await msg.bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id,
                text=_collection_card(items)
            )
        except Exception:
            pass
    # Keep the user's link message — don't delete it

# ── Done → password ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "zip_done")
async def cb_zip_done(cb: CallbackQuery, state: FSMContext):
    data  = await state.get_data()
    items = data.get("items", [])

    if not items:
        await cb.answer("⚠️ Add at least one file or link first!", show_alert=True)
        return

    await state.set_state(ZipStates.waiting_password)
    await cb.message.edit_text(
        f"🔒 <b>Set ZIP Password?</b>\n"
        f"┌─────────────────────────\n"
        f"│ 📂 <b>{len(items)} item(s)</b> ready\n"
        f"│\n"
        f"│ Type a password below, or\n"
        f"│ tap <b>⏭ Skip Password</b>.\n"
        f"└─────────────────────────"
    )
    await state.update_data(status_msg_id=cb.message.message_id)
    # Show reply keyboard with Skip + Cancel
    await cb.message.answer("🔒 Password step:", reply_markup=_zip_password_reply_kb())
    await cb.answer()


# ── Password: text input ───────────────────────────────────────────────────────

@router.message(ZipStates.waiting_password)
async def on_zip_password(msg: Message, state: FSMContext):
    # "⏭ Skip Password" button comes in as text — handle it here
    text = (msg.text or "").strip()
    if text == "⏭ Skip Password":
        await _go_to_rename(msg, state, password=None)
        return

    password     = text
    await _go_to_rename(msg, state, password=password, delete_msg=True)


async def _go_to_rename(msg: Message, state: FSMContext, password, delete_msg: bool = False):
    default_name = _default_zip_name()
    await state.update_data(password=password, default_name=default_name)
    await state.set_state(ZipStates.waiting_name)

    if delete_msg:
        try:
            await msg.delete()
        except Exception:
            pass

    data          = await state.get_data()
    status_msg_id = data.get("status_msg_id")
    chat_id       = data.get("chat_id") or msg.chat.id

    lock_icon = "🔒 Password set!" if password else "🔓 No password"
    name_text = (
        f"📝 <b>Name Your ZIP</b>\n"
        f"┌─────────────────────────\n"
        f"│ {lock_icon}\n"
        f"│\n"
        f"│ Type a name below, or tap\n"
        f"│ <b>✅ Keep: {default_name[:20]}</b>\n"
        f"└─────────────────────────"
    )
    # Edit status card (no inline buttons needed — reply kb handles everything)
    if status_msg_id:
        try:
            await msg.bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id, text=name_text
            )
        except Exception:
            pass
    # Swap reply keyboard to rename kb
    await msg.answer("📝 Name step:", reply_markup=_zip_rename_reply_kb(default_name))


@router.callback_query(F.data == "zip_skip_password")
async def cb_skip_password(cb: CallbackQuery, state: FSMContext):
    # Inline Skip button fallback (still works if user has old keyboard)
    await cb.answer()
    await _go_to_rename(cb.message, state, password=None)


# ── Name: keep default or rename ──────────────────────────────────────────────

@router.callback_query(F.data == "zip_default_name")
async def cb_default_name(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data     = await state.get_data()
    zip_name = data.get("default_name", _default_zip_name())
    await state.update_data(zip_name=zip_name)
    await state.set_state(ZipStates.building)
    await cb.answer()
    await _start_zip_build(cb.message, state, bot, cb.from_user.id)


@router.callback_query(F.data == "zip_rename")
async def cb_zip_rename(cb: CallbackQuery, state: FSMContext):
    await state.set_state(ZipStates.waiting_name)
    await cb.message.edit_text(
        "✏️ <b>Enter ZIP Name</b>\n"
        "┌─────────────────────────\n"
        "│ Type your filename.\n"
        "│ <i>.zip added automatically</i>\n"
        "└─────────────────────────",
        reply_markup=cancel_kb("zip_cancel")
    )
    await state.update_data(status_msg_id=cb.message.message_id)
    await cb.answer()


@router.message(ZipStates.waiting_name)
async def on_zip_name(msg: Message, state: FSMContext, bot: Bot):
    text = (msg.text or "").strip()

    # "✅ Keep: <name>" button — extract actual name
    if text.startswith("✅ Keep:") or text.startswith("✅ Keep："):
        data     = await state.get_data()
        zip_name = data.get("default_name", _default_zip_name())
    elif not text:
        await msg.answer("⚠️ Please send a valid filename.")
        return
    else:
        zip_name = text
        if not zip_name.lower().endswith(".zip"):
            zip_name += ".zip"

    await state.update_data(zip_name=zip_name)
    await state.set_state(ZipStates.building)

    try:
        await msg.delete()
    except Exception:
        pass

    await _start_zip_build(msg, state, bot, msg.from_user.id)


# ── Build ──────────────────────────────────────────────────────────────────────

async def _start_zip_build(trigger_msg: Message, state: FSMContext, bot: Bot, user_id: int):
    data      = await state.get_data()
    items     = data.get("items", [])
    zip_name  = data.get("zip_name", _default_zip_name())
    password  = data.get("password")
    chat_id   = data.get("chat_id") or trigger_msg.chat.id

    user           = await db.async_get_user(user_id)
    user_hash      = user.get("hash", "")
    user_path      = user.get("default_path", "")
    compress_level = int(user.get("zip_compress_level", 6))

    task_key = f"zip_{user_id}"

    async def _build():
        # Remove reply keyboard, send single status card
        await bot.send_message(chat_id, "🗜 <b>Building ZIP…</b>", reply_markup=ReplyKeyboardRemove())
        status_msg = await bot.send_message(
            chat_id,
            "🗜 <b>ZIP · Starting</b>\n"
            "┌─────────────────────────\n"
            "│ ⏳ Preparing downloads…\n"
            "└─────────────────────────",
            reply_markup=cancel_kb(f"zip_cancel_build_{user_id}")
        )

        zip_dir   = _zip_temp_dir(user_id)
        files_dir = os.path.join(zip_dir, "files")
        os.makedirs(files_dir, exist_ok=True)
        zip_path    = os.path.join(zip_dir, zip_name)
        total_files = len(items)

        try:
            # ── Phase 1: Parallel downloads ──────────────────────────────────
            # Shared progress tracking
            progress_map  = {i: (0, 0) for i in range(total_files)}  # {idx: (done, total)}
            progress_lock = asyncio.Lock()
            last_upd      = [0.0]
            start_dl      = time.time()

            async def _report_progress(idx: int, fname: str):
                now = time.time()
                if now - last_upd[0] < 2.0:
                    return
                last_upd[0] = now
                async with progress_lock:
                    done_sum  = sum(d for d, _ in progress_map.values())
                    total_sum = sum(t for _, t in progress_map.values()) or 1
                elapsed = now - start_dl
                speed   = done_sum / elapsed if elapsed > 0 else 0
                # Show which file is "current" (first incomplete)
                current_idx  = next(
                    (i for i, (d, t) in progress_map.items() if t > 0 and d < t),
                    idx
                )
                current_name = items[current_idx].get("name", fname)
                card = formatting.zip_progress_card(
                    current_name, current_idx + 1, total_files,
                    done_sum, total_sum, speed, elapsed, "Downloading"
                )
                await _safe_edit(status_msg, card)

            async def _download_item(idx: int, item: dict) -> str:
                fname = item.get("name") or f"file_{idx + 1}"
                dest  = _unique_dest(files_dir, fname)

                async def _cb(done, total, speed, elapsed):
                    async with progress_lock:
                        progress_map[idx] = (done, total)
                    await _report_progress(idx, fname)

                if item["type"] == "tg_file":
                    file_size = int(item.get("size", 0))
                    await download_tg_file(bot, item["file_id"], file_size, dest, _cb)
                elif item["type"] == "link":
                    await downloader.download_file(item["url"], dest, _cb)

                async with progress_lock:
                    sz = os.path.getsize(dest) if os.path.exists(dest) else 0
                    progress_map[idx] = (sz, sz)

                return dest

            # Run downloads with bounded concurrency
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_DL)

            async def _bounded(idx: int, item: dict) -> str:
                async with semaphore:
                    return await _download_item(idx, item)

            downloaded_paths = await asyncio.gather(
                *[_bounded(i, item) for i, item in enumerate(items)]
            )

            # ── Phase 2: Create ZIP ──────────────────────────────────────────
            # Show compress start card
            total_dl_size = sum(
                os.path.getsize(p) for p in downloaded_paths if os.path.exists(p)
            )
            await _safe_edit(
                status_msg,
                formatting.compress_progress_card(zip_name, 0, total_dl_size, compress_level),
                cancel_kb(f"zip_cancel_build_{user_id}")
            )

            password_used = False
            if password:
                password_used = _make_zip_password(zip_path, list(downloaded_paths), compress_level, password)
                if not password_used:
                    _make_zip(zip_path, list(downloaded_paths), compress_level)
                    await bot.send_message(
                        chat_id,
                        "⚠️ <b>pyminizip not available</b> — ZIP created <b>without password</b>."
                    )
            else:
                _make_zip(zip_path, list(downloaded_paths), compress_level)

            # Show compress done card (total = final zip size)
            zip_size_after = os.path.getsize(zip_path) if os.path.exists(zip_path) else 0
            await _safe_edit(
                status_msg,
                formatting.compress_progress_card(zip_name, total_dl_size, total_dl_size, compress_level),
                cancel_kb(f"zip_cancel_build_{user_id}")
            )

            if not os.path.exists(zip_path) or os.path.getsize(zip_path) == 0:
                raise RuntimeError("ZIP file was not created or is empty.")

            # ── Phase 3: Upload ZIP ──────────────────────────────────────────
            zip_size = os.path.getsize(zip_path)
            start_ul = time.time()
            last_ul  = [0.0]

            async def ul_progress(done, total):
                now = time.time()
                if now - last_ul[0] < 2.0:
                    return
                last_ul[0] = now
                elapsed = time.time() - start_ul
                speed   = done / elapsed if elapsed > 0 else 0
                card    = formatting.zip_progress_card(
                    zip_name, total_files, total_files,
                    done, total, speed, elapsed, "Uploading ZIP"
                )
                await _safe_edit(status_msg, card)

            await _safe_edit(
                status_msg,
                formatting.zip_progress_card(
                    zip_name, total_files, total_files, 0, zip_size, 0, 0, "Uploading ZIP"
                )
            )

            result   = await viking_api.upload_file_multipart(
                zip_path, zip_name, user_hash, user_path, ul_progress
            )
            if user_path:
                await db.async_remember_path(user_id, user_path)

            res_name = result.get("name") or zip_name
            res_size = result.get("size") or zip_size
            res_url  = result.get("_url") or ""
            res_hash = result.get("hash") or ""

            await _safe_edit(
                status_msg,
                formatting.zip_success_card(
                    res_name, res_size, res_url, res_hash, total_files,
                    password_protected=bool(password and password_used),
                    user_hash=user_hash,
                ),
                None
            )
            await log_upload(
                bot, user_id, trigger_msg.from_user.username, trigger_msg.from_user.first_name,
                res_name, res_size, res_url, res_hash, user_hash,
                zip_file=True, file_count=total_files,
            )

        except asyncio.CancelledError:
            await _safe_edit(status_msg, "⛔ <b>ZIP build cancelled.</b>", None)
        except Exception as e:
            await _safe_edit(
                status_msg,
                formatting.error_card("ZIP Build Failed", str(e)[:300]),
                None
            )
        finally:
            task_manager.done(task_key)
            await state.clear()
            if user.get("auto_delete_temp", True):
                shutil.rmtree(zip_dir, ignore_errors=True)

    task = asyncio.create_task(_build())
    task_manager.register(task_key, task)


# ── Cancel buttons ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "zip_cancel")
async def cb_zip_cancel(cb: CallbackQuery, state: FSMContext):
    user_id = cb.from_user.id
    task_manager.cancel(f"zip_{user_id}")
    await state.clear()
    await cb.message.edit_text("⛔ <b>ZIP cancelled.</b>", reply_markup=None)
    await cb.message.answer("Cancelled.", reply_markup=ReplyKeyboardRemove())
    await cb.answer("Cancelled")


@router.message(Command("done"))
@router.message(F.text == "✅ Done")
async def cmd_zip_done(msg: Message, state: FSMContext, bot: Bot):
    """Handle /done command and Done button during ZIP collection."""
    current = await state.get_state()
    if current != ZipStates.collecting:
        await msg.answer("No active ZIP session.", reply_markup=ReplyKeyboardRemove())
        return
    data  = await state.get_data()
    items = data.get("items", [])
    if not items:
        await msg.answer("⚠️ Add at least one file or URL first.")
        return
    # Simulate zip_done flow — ask for password
    await state.set_state(ZipStates.waiting_password)
    sent = await msg.answer(
        f"🔒 <b>Set ZIP Password?</b>\n"
        f"┌─────────────────────────\n"
        f"│ 📂 <b>{len(items)} item(s)</b> ready\n"
        f"│\n"
        f"│ Type a password below, or\n"
        f"│ tap <b>⏭ Skip Password</b>.\n"
        f"└─────────────────────────"
    )
    await msg.answer("🔒 Password step:", reply_markup=_zip_password_reply_kb())
    await state.update_data(status_msg_id=sent.message_id, chat_id=msg.chat.id)


@router.message(Command("cancel"))
@router.message(F.text == "❌ Cancel ZIP")
async def cmd_zip_cancel_text(msg: Message, state: FSMContext):
    """Handle /cancel and Cancel ZIP button during any ZIP phase."""
    current = await state.get_state()
    if current not in (ZipStates.collecting, ZipStates.waiting_password, ZipStates.waiting_name):
        if msg.text in ("✅ Done", "❌ Cancel ZIP", "⏭ Skip Password") or (msg.text or "").startswith("✅ Keep:"):
            await msg.answer("No active ZIP session.", reply_markup=ReplyKeyboardRemove())
        return
    from utils import task_manager as tm
    tm.cancel_all_for_user(msg.from_user.id)
    await state.clear()
    await msg.answer("⛔ <b>ZIP cancelled.</b>", reply_markup=ReplyKeyboardRemove())


@router.callback_query(F.data.startswith("zip_cancel_build_"))
async def cb_zip_cancel_build(cb: CallbackQuery, state: FSMContext):
    user_id = cb.from_user.id
    task_manager.cancel(f"zip_{user_id}")
    await state.clear()
    await cb.message.edit_text("⛔ <b>ZIP build cancelled.</b>", reply_markup=None)
    await cb.answer("Cancelled")
