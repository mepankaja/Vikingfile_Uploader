from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from keyboards.buttons import settings_kb, zip_level_kb, settings_input_kb, main_menu_kb
from utils import db, formatting

router = Router()


class SettingsStates(StatesGroup):
    waiting_hash = State()
    waiting_path = State()


def _card(user: dict) -> str:
    h = user.get("hash", "") or ""
    p = user.get("default_path", "") or ""
    z = user.get("zip_compress_level", 6)

    # Keep <code> and <i> separate — no nesting
    if h:
        h_line = f"│   <code>{formatting._esc(h[:32])}</code>"
    else:
        h_line = "│   <i>❌ Not set — uploads won't work!</i>"

    p_line = f"│   <code>{formatting._esc(p[:32])}</code>" if p else "│   <i>📂 Root (default)</i>"

    return (
        f"⚙️ <b>Settings</b>\n"
        f"┌─────────────────────────\n"
        f"│ 🔑 <b>User Hash</b>\n"
        f"{h_line}\n"
        f"│\n"
        f"│ 📂 <b>Upload Path</b>\n"
        f"{p_line}\n"
        f"│\n"
        f"│ 🗜 <b>ZIP Level</b>   {z}\n"
        f"└─────────────────────────"
    )


@router.callback_query(F.data == "menu_settings")
async def cb_settings(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db.async_get_user(cb.from_user.id)
    try:
        await cb.message.edit_text(_card(user), reply_markup=settings_kb(user))
    except Exception:
        await cb.message.answer(_card(user), reply_markup=settings_kb(user))
    await cb.answer()


# ── Hash ───────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings_hash")
async def cb_set_hash(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SettingsStates.waiting_hash)
    await cb.message.edit_text(
        "🔑 <b>Set User Hash</b>\n"
        "┌─────────────────────────\n"
        "│ Send your VikingFile user hash.\n"
        "│\n"
        "│ <b>Where to find it:</b>\n"
        "│ 1️⃣ Go to <a href=\"https://vikingfile.com\">vikingfile.com</a>\n"
        "│ 2️⃣ Log in → open ⚙️ Settings\n"
        "│ 3️⃣ Copy your <b>User Hash</b> and\n"
        "│    paste it here\n"
        "└─────────────────────────",
        reply_markup=settings_input_kb(),
        disable_web_page_preview=True,
    )
    await cb.answer()


@router.message(SettingsStates.waiting_hash)
async def on_hash_input(msg: Message, state: FSMContext):
    val = (msg.text or "").strip()
    if not val:
        await msg.answer("⚠️ Please send a valid hash string.")
        return
    await db.async_set_user_field(msg.from_user.id, "hash", val)
    await state.clear()
    user = await db.async_get_user(msg.from_user.id)
    await msg.answer(
        f"✅ <b>Hash Saved!</b>\n"
        f"┌─────────────────────────\n"
        f"│ <code>{formatting._esc(val[:32])}</code>\n"
        f"└─────────────────────────\n"
        f"<i>You can now upload files.</i>",
        reply_markup=settings_kb(user),
    )


# ── Path ───────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings_path")
async def cb_set_path(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SettingsStates.waiting_path)
    await cb.message.edit_text(
        "📂 <b>Set Upload Path</b>\n"
        "┌─────────────────────────\n"
        "│ Send a folder path to organise\n"
        "│ your uploads on VikingFile.\n"
        "│\n"
        "│ <b>Example:</b> <code>Telegram/Bot</code>\n"
        "│\n"
        "│ Send <code>-</code> to reset to root.\n"
        "└─────────────────────────",
        reply_markup=settings_input_kb(),
    )
    await cb.answer()


@router.message(SettingsStates.waiting_path)
async def on_path_input(msg: Message, state: FSMContext):
    path = (msg.text or "").strip()
    if path == "-":
        path = ""
    await db.async_set_user_field(msg.from_user.id, "default_path", path)
    await state.clear()
    user  = await db.async_get_user(msg.from_user.id)
    label = path or "Root"
    await msg.answer(
        f"✅ <b>Path Saved!</b>\n"
        f"┌─────────────────────────\n"
        f"│ <code>{formatting._esc(label)}</code>\n"
        f"└─────────────────────────",
        reply_markup=settings_kb(user),
    )


# ── ZIP Level ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings_zip_level")
async def cb_zip_level(cb: CallbackQuery):
    user = await db.async_get_user(cb.from_user.id)
    await cb.message.edit_text(
        "🗜 <b>ZIP Compression Level</b>\n"
        "┌─────────────────────────\n"
        "│ Higher = smaller file, longer wait.\n"
        "└─────────────────────────",
        reply_markup=zip_level_kb(user.get("zip_compress_level", 6)),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("zip_level_"))
async def cb_set_zip_level(cb: CallbackQuery):
    level = int(cb.data.split("_")[-1])
    await db.async_set_user_field(cb.from_user.id, "zip_compress_level", level)
    user = await db.async_get_user(cb.from_user.id)
    await cb.message.edit_text(_card(user), reply_markup=settings_kb(user))
    await cb.answer(f"✅ Level {level} set")


# ── Cancel ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings_cancel")
async def cb_settings_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db.async_get_user(cb.from_user.id)
    await cb.message.edit_text(_card(user), reply_markup=settings_kb(user))
    await cb.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()


# ── /settings command ──────────────────────────────────────────────────────────

from aiogram.filters import Command

@router.message(Command("settings"))
async def cmd_settings(msg: Message, state: FSMContext):
    current = await state.get_state()
    if current in (SettingsStates.waiting_hash, SettingsStates.waiting_path):
        # User is mid-input — remind them rather than silently resetting
        field = "hash" if current == SettingsStates.waiting_hash else "upload path"
        await msg.answer(
            f"⚠️ <b>Waiting for your {field}</b>\n"
            f"Please send the value now, or tap ❌ Cancel below.",
            reply_markup=settings_input_kb(),
        )
        return
    await state.clear()
    user = await db.async_get_user(msg.from_user.id)
    await msg.answer(_card(user), reply_markup=settings_kb(user))
