"""
/myfiles — browse VikingFile account files & folders, extract links.

VikingFile's list-files API accepts an optional "path" parameter to browse
into a folder/subfolder (e.g. "Telegram/Movies"). There is no separate
list-folders endpoint — folders are just path prefixes you navigate into
by typing the path you want.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from keyboards.buttons import files_nav_kb, files_goto_kb, known_folders_kb, back_to_menu_kb, main_menu_kb
from utils import db, formatting, viking_api

router = Router()


class FilesStates(StatesGroup):
    waiting_path = State()


def _breadcrumb(path: str) -> str:
    if not path:
        return "📂 <b>Root</b>"
    parts = [p for p in path.split("/") if p]
    return "📂 <b>Root</b> / " + " / ".join(f"<b>{formatting._esc(p)}</b>" for p in parts)


def _list_card(files: list, page: int, max_pages: int, path: str) -> str:
    crumb = _breadcrumb(path)
    if not files:
        return (
            f"📁 <b>My Files</b>\n"
            f"{crumb}\n"
            f"┌─────────────────────────\n"
            f"│ <i>No files in this folder.</i>\n"
            f"└─────────────────────────"
        )
    header = (
        f"📁 <b>My Files</b>  <i>· page {page}/{max_pages}</i>\n"
        f"{crumb}\n"
        f"─────────────────────────\n"
    )
    items = []
    for i, f in enumerate(files, 1):
        items.append(
            f"{i}. " + formatting.file_list_item(
                f.get("name", "?"), f.get("size", 0),
                f.get("downloads", 0), f.get("created", ""), f.get("hash", "")
            )
        )
    return header + "\n\n".join(items)


async def _show(target, user_id: int, page: int, path: str, edit: bool):
    user_hash = await db.async_get_hash(user_id)
    if not user_hash:
        text = formatting.setup_required_card()
        kb   = back_to_menu_kb()
        if edit: await target.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
        else:    await target.answer(text, reply_markup=kb, disable_web_page_preview=True)
        return

    try:
        data      = await viking_api.list_files(user_hash, page, path=path)
        files     = data.get("files", [])
        cur_page  = data.get("currentPage", page)
        max_pages = max(data.get("maxPages", 1), 1)
        if path and files:
            await db.async_remember_path(user_id, path)
        user = await db.async_get_user(user_id)
        has_known = bool(user.get("known_paths"))
        card = _list_card(files, cur_page, max_pages, path)
        kb   = files_nav_kb(cur_page, max_pages, path, has_files=bool(files), has_known_folders=has_known)
        if edit: await target.edit_text(card, reply_markup=kb, disable_web_page_preview=True)
        else:    await target.answer(card, reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        text = formatting.error_card("Could not load files", str(e)[:120])
        kb   = back_to_menu_kb()
        if edit: await target.edit_text(text, reply_markup=kb)
        else:    await target.answer(text, reply_markup=kb)


@router.message(Command("myfiles"))
async def cmd_myfiles(msg: Message, state: FSMContext):
    await state.update_data(files_path="")
    await _show(msg, msg.from_user.id, 1, "", edit=False)


@router.callback_query(F.data == "menu_myfiles")
async def cb_myfiles(cb: CallbackQuery, state: FSMContext):
    await state.update_data(files_path="")
    await _show(cb.message, cb.from_user.id, 1, "", edit=True)
    await cb.answer()


@router.callback_query(F.data.startswith("files_page_"))
async def cb_files_page(cb: CallbackQuery, state: FSMContext):
    page = int(cb.data.split("_")[-1])
    data = await state.get_data()
    path = data.get("files_path", "")
    await _show(cb.message, cb.from_user.id, page, path, edit=True)
    await cb.answer()


@router.callback_query(F.data == "files_up")
async def cb_files_up(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    path = data.get("files_path", "")
    parts = [p for p in path.split("/") if p]
    new_path = "/".join(parts[:-1])
    await state.update_data(files_path=new_path)
    await _show(cb.message, cb.from_user.id, 1, new_path, edit=True)
    await cb.answer()


@router.callback_query(F.data == "files_goto")
async def cb_files_goto(cb: CallbackQuery, state: FSMContext):
    await state.set_state(FilesStates.waiting_path)
    await cb.message.edit_text(
        "📂 <b>Go to Folder</b>\n"
        "┌─────────────────────────\n"
        "│ Type a folder path, e.g.\n"
        "│ <code>Telegram/Movies</code>\n"
        "│\n"
        "│ Send <code>-</code> to go to Root.\n"
        "└─────────────────────────",
        reply_markup=files_goto_kb()
    )
    await state.update_data(status_msg_id=cb.message.message_id, chat_id=cb.message.chat.id)
    await cb.answer()


@router.message(StateFilter(FilesStates.waiting_path))
async def on_goto_path(msg: Message, state: FSMContext):
    path = (msg.text or "").strip()
    if path == "-":
        path = ""
    path = path.strip("/")
    await state.update_data(files_path=path)
    await state.set_state(None)

    try:
        await msg.delete()
    except Exception:
        pass

    data          = await state.get_data()
    status_msg_id = data.get("status_msg_id")
    chat_id       = data.get("chat_id") or msg.chat.id

    if status_msg_id:
        try:
            user_hash = await db.async_get_hash(msg.from_user.id)
            if not user_hash:
                await msg.bot.edit_message_text(
                    chat_id=chat_id, message_id=status_msg_id,
                    text=formatting.setup_required_card(),
                    reply_markup=back_to_menu_kb(), disable_web_page_preview=True,
                )
                return
            data2     = await viking_api.list_files(user_hash, 1, path=path)
            files     = data2.get("files", [])
            cur_page  = data2.get("currentPage", 1)
            max_pages = max(data2.get("maxPages", 1), 1)
            if path and files:
                await db.async_remember_path(msg.from_user.id, path)
            user      = await db.async_get_user(msg.from_user.id)
            has_known = bool(user.get("known_paths"))
            card = _list_card(files, cur_page, max_pages, path)
            kb   = files_nav_kb(cur_page, max_pages, path, has_files=bool(files), has_known_folders=has_known)
            await msg.bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id, text=card,
                reply_markup=kb, disable_web_page_preview=True,
            )
            return
        except Exception:
            pass

    await _show(msg, msg.from_user.id, 1, path, edit=False)


@router.callback_query(F.data == "files_goto_cancel")
async def cb_goto_cancel(cb: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    data = await state.get_data()
    path = data.get("files_path", "")
    await _show(cb.message, cb.from_user.id, 1, path, edit=True)
    await cb.answer("Cancelled")


@router.callback_query(F.data == "files_known")
async def cb_files_known(cb: CallbackQuery):
    """
    VikingFile's API has no list-folders endpoint — folders can only be
    browsed if you already know the path. We track every path this user
    has uploaded to or visited and offer them here as quick shortcuts.
    """
    user = await db.async_get_user(cb.from_user.id)
    paths = user.get("known_paths", [])
    if not paths:
        await cb.answer("No known folders yet — upload to a folder first.", show_alert=True)
        return
    await cb.message.edit_text(
        "📁 <b>My Known Folders</b>\n"
        "┌─────────────────────────\n"
        "│ VikingFile doesn't expose a folder\n"
        "│ list, so these are folders <b>you've</b>\n"
        "│ previously uploaded to or visited.\n"
        "└─────────────────────────",
        reply_markup=known_folders_kb(paths)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("files_kf_"))
async def cb_files_kf_select(cb: CallbackQuery, state: FSMContext):
    idx  = int(cb.data.split("_")[-1])
    user = await db.async_get_user(cb.from_user.id)
    paths = user.get("known_paths", [])
    if idx >= len(paths):
        await cb.answer("That folder is no longer in your list.", show_alert=True)
        return
    path = paths[idx]
    await state.update_data(files_path=path)
    await _show(cb.message, cb.from_user.id, 1, path, edit=True)
    await cb.answer()


@router.callback_query(F.data == "files_extract")
async def cb_files_extract(cb: CallbackQuery, state: FSMContext):
    """Extract every file link in the current folder across all pages."""
    user_id   = cb.from_user.id
    user_hash = await db.async_get_hash(user_id)
    if not user_hash:
        await cb.answer("Set your User Hash in Settings first.", show_alert=True)
        return

    data = await state.get_data()
    path = data.get("files_path", "")

    await cb.answer("Extracting links…")
    progress_msg = await cb.message.answer("🔗 <b>Extracting links…</b>  <i>please wait</i>")

    try:
        all_links = []
        page = 1
        while True:
            res       = await viking_api.list_files(user_hash, page, path=path)
            files     = res.get("files", [])
            max_pages = max(res.get("maxPages", 1), 1)
            for f in files:
                name = f.get("name", "?")
                url  = f.get("_url") or (f"https://vikingfile.com/f/{f['hash']}" if f.get("hash") else "")
                if url:
                    all_links.append(f"{name} — {url}")
            if page >= max_pages or not files:
                break
            page += 1
            if page > 50:  # safety cap
                break

        if not all_links:
            await progress_msg.edit_text("⚠️ No files with links found in this folder.")
            return

        crumb = _breadcrumb(path).replace("<b>", "").replace("</b>", "")
        body  = "\n".join(all_links)
        text  = f"🔗 <b>Extracted Links</b>\n{crumb}\n\n<blockquote expandable>{formatting._esc(body)}</blockquote>"

        # Telegram message limit safety — split if too long
        if len(text) > 4000:
            await progress_msg.edit_text(
                f"🔗 <b>Extracted {len(all_links)} Links</b>\n{crumb}\n\n"
                f"<i>Too many to show inline — sending as a file.</i>"
            )
            import io
            buf = io.BytesIO("\n".join(all_links).encode("utf-8"))
            buf.name = "links.txt"
            from aiogram.types import BufferedInputFile
            await cb.message.answer_document(
                BufferedInputFile(buf.read(), filename="links.txt"),
                caption=f"🔗 {len(all_links)} links extracted from {path or 'Root'}"
            )
        else:
            await progress_msg.edit_text(text, disable_web_page_preview=True)

    except Exception as e:
        await progress_msg.edit_text(formatting.error_card("Extraction Failed", str(e)[:200]))
