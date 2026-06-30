from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗜 ZIP",       callback_data="menu_zip"),
            InlineKeyboardButton(text="📁 My Files",  callback_data="menu_myfiles"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Settings",  callback_data="menu_settings"),
            InlineKeyboardButton(text="📖 Help",       callback_data="menu_help"),
        ],
    ])


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu_main")],
    ])


def cancel_kb(action: str = "cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data=action)],
    ])


def cancel_and_menu_kb(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Cancel",     callback_data=action),
            InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu_main"),
        ],
    ])


def setup_required_kb() -> InlineKeyboardMarkup:
    """Shown when VikingFile returns 'bad user' — guides to settings."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Open Settings", callback_data="menu_settings")],
        [InlineKeyboardButton(text="🏠 Main Menu",     callback_data="menu_main")],
    ])


# ── Settings ───────────────────────────────────────────────────────────────────

def settings_kb(user: dict) -> InlineKeyboardMarkup:
    zip_lvl  = user.get("zip_compress_level", 6)
    hash_set = "✅" if user.get("hash") else "❌"
    path_set = "✅" if user.get("default_path") else "📂"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{hash_set}  User Hash",
            callback_data="settings_hash"
        )],
        [InlineKeyboardButton(
            text=f"{path_set}  Upload Path",
            callback_data="settings_path"
        )],
        [InlineKeyboardButton(
            text=f"🗜  ZIP Compression  ·  Level {zip_lvl}",
            callback_data="settings_zip_level"
        )],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu_main")],
    ])


def zip_level_kb(current: int) -> InlineKeyboardMarkup:
    levels = [
        (0, "🚀 Level 0  —  fastest, no compression"),
        (3, "⚡ Level 3  —  fast"),
        (6, "⚖️ Level 6  —  balanced  (recommended)"),
        (9, "🔬 Level 9  —  smallest size"),
    ]
    rows = []
    for lvl, label in levels:
        prefix = "● " if lvl == current else "  "
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{label}", callback_data=f"zip_level_{lvl}"
        )])
    rows.append([InlineKeyboardButton(text="← Back", callback_data="menu_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_input_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="settings_cancel")],
    ])


# ── ZIP ────────────────────────────────────────────────────────────────────────

def zip_collection_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Done  →  Build ZIP", callback_data="zip_done")],
        [InlineKeyboardButton(text="❌ Cancel",              callback_data="zip_cancel")],
    ])


def zip_password_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Skip  —  No Password", callback_data="zip_skip_password")],
        [InlineKeyboardButton(text="❌ Cancel",                callback_data="zip_cancel")],
    ])


def zip_rename_kb(default_name: str) -> InlineKeyboardMarkup:
    short = default_name if len(default_name) <= 30 else default_name[:27] + "…"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Keep: {short}",  callback_data="zip_default_name")],
        [InlineKeyboardButton(text="✏️ Rename",           callback_data="zip_rename")],
        [InlineKeyboardButton(text="❌ Cancel",            callback_data="zip_cancel")],
    ])


# ── My Files ───────────────────────────────────────────────────────────────────

def files_nav_kb(page: int, max_pages: int, path: str = "", has_files: bool = False, has_known_folders: bool = False) -> InlineKeyboardMarkup:
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀ Prev", callback_data=f"files_page_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"📄 {page} / {max_pages}", callback_data="noop"))
    if page < max_pages:
        nav.append(InlineKeyboardButton(text="Next ▶", callback_data=f"files_page_{page+1}"))

    rows = [nav]

    action_row = []
    if path:
        action_row.append(InlineKeyboardButton(text="⬆ Up a folder", callback_data="files_up"))
    action_row.append(InlineKeyboardButton(text="📂 Go to folder", callback_data="files_goto"))
    rows.append(action_row)

    if has_known_folders:
        rows.append([InlineKeyboardButton(text="📁 My Known Folders", callback_data="files_known")])

    if has_files:
        rows.append([InlineKeyboardButton(text="🔗 Extract All Links", callback_data="files_extract")])

    rows.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def files_goto_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="files_goto_cancel")],
    ])


def known_folders_kb(paths: list) -> InlineKeyboardMarkup:
    rows = []
    for i, p in enumerate(paths[:15]):
        label = p if len(p) <= 32 else p[:29] + "…"
        rows.append([InlineKeyboardButton(text=f"📂 {label}", callback_data=f"files_kf_{i}")])
    rows.append([InlineKeyboardButton(text="← Back", callback_data="menu_myfiles")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
