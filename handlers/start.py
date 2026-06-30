from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from keyboards.buttons import main_menu_kb

router = Router()

WELCOME = (
    "🚀 <b>NXT Viking Bot</b>\n"
    "┌─────────────────────────\n"
    "│ Upload files &amp; links to\n"
    "│ <b>VikingFile</b> — fast &amp; free!\n"
    "└─────────────────────────\n"
    "\n"
    "📎 <b>Send a file</b> → instant upload\n"
    "🔗 <b>Paste a URL</b> → remote fetch\n"
    "🗜 <b>ZIP</b> → bundle multiple files\n"
    "\n"
    "<i>Use /help to see all commands.</i>\n"
    "\n"
    "✨ Powered by <a href=\"https://t.me/NXT_HUB\"><b>@NXT_HUB</b></a>"
)

HELP_TEXT = (
    "📖 <b>NXT Viking — Help</b>\n"
    "┌─────────────────────────\n"
    "│\n"
    "│ <b>Uploading</b>\n"
    "│ • Send any file (up to 20 MB via Telegram)\n"
    "│ • Paste a direct URL → VikingFile fetches it\n"
    "│   on their servers (no size limit!)\n"
    "│\n"
    "│ <b>ZIP Builder</b>  🗜\n"
    "│ • Tap ZIP in the menu\n"
    "│ • Send files &amp; URLs one by one\n"
    "│ • Tap <i>Done → Build ZIP</i> when ready\n"
    "│ • Optionally set a password\n"
    "│\n"
    "│ <b>My Files</b>  📁\n"
    "│ • Browse all your VikingFile uploads\n"
    "│ • Requires your User Hash to be set\n"
    "│\n"
    "│ <b>Settings</b>  ⚙️\n"
    "│ • <b>User Hash</b> — links your VikingFile\n"
    "│   account (get it at vikingfile.com)\n"
    "│ • <b>Upload Path</b> — organise uploads\n"
    "│   into folders (e.g. <code>Telegram/Bot</code>)\n"
    "│ • <b>ZIP Level</b> — 0 = fast, 9 = smallest\n"
    "│\n"
    "│ <b>Commands</b>\n"
    "│ /start    🏠 Main menu\n"
    "│ /help     📖 This help message\n"
    "│ /zip      🗜 Start a ZIP session\n"
    "│ /myfiles  📁 Your uploaded files\n"
    "│ /settings ⚙️ Bot settings\n"
    "│ /cancel   ❌ Cancel current task\n"
    "│\n"
    "└─────────────────────────\n"
    "\n"
    "⚠️ <b>First time?</b>  Go to ⚙️ Settings → <b>User Hash</b>\n"
    "to link your VikingFile account so uploads are\n"
    "saved to your library.\n"
    "\n"
    "✨ Powered by <a href=\"https://t.me/NXT_HUB\"><b>@NXT_HUB</b></a>"
)


@router.message(CommandStart())
async def cmd_start(msg: Message):
    await msg.answer(WELCOME, reply_markup=main_menu_kb(), disable_web_page_preview=True)


@router.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(HELP_TEXT, reply_markup=main_menu_kb(), disable_web_page_preview=True)


@router.callback_query(F.data == "menu_main")
async def cb_main_menu(cb: CallbackQuery):
    try:
        await cb.message.edit_text(WELCOME, reply_markup=main_menu_kb(), disable_web_page_preview=True)
    except Exception:
        await cb.message.answer(WELCOME, reply_markup=main_menu_kb(), disable_web_page_preview=True)
    await cb.answer()


@router.callback_query(F.data == "menu_help")
async def cb_help(cb: CallbackQuery):
    try:
        await cb.message.edit_text(HELP_TEXT, reply_markup=main_menu_kb(), disable_web_page_preview=True)
    except Exception:
        await cb.message.answer(HELP_TEXT, reply_markup=main_menu_kb(), disable_web_page_preview=True)
    await cb.answer()


@router.callback_query(F.data == "check_sub")
async def cb_check_sub(cb: CallbackQuery):
    from middlewares.subscription import _is_member, _verified
    if await _is_member(cb.bot, cb.from_user.id):
        _verified.add(cb.from_user.id)
        await cb.message.edit_text(WELCOME, reply_markup=main_menu_kb(), disable_web_page_preview=True)
        await cb.answer("Welcome!")
    else:
        await cb.answer("You haven't joined @NXT_HUB yet.", show_alert=True)
