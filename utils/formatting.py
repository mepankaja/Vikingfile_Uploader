import math
import time
from typing import Optional
from utils.file_icons import get_file_icon


# ── Helpers ────────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_size(b) -> str:
    b = int(b or 0)
    if b <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = min(int(math.floor(math.log(max(b, 1), 1024))), len(units) - 1)
    return f"{round(b / math.pow(1024, i), 2)} {units[i]}"


def format_speed(bps: float) -> str:
    return f"{format_size(int(bps))}/s"


def format_eta(sec: float) -> str:
    if sec < 0 or sec > 86400 * 7:
        return "—"
    sec = int(sec)
    if sec < 60:   return f"{sec}s"
    if sec < 3600: m, s = divmod(sec, 60);  return f"{m}m {s}s"
    h, r = divmod(sec, 3600); m, s = divmod(r, 60); return f"{h}h {m}m"


def _pct(cur: int, total: int) -> str:
    if total <= 0: return "…"
    return f"{min(100, int(cur / total * 100))}%"


def _bar(cur: int, total: int, w: int = 14) -> str:
    cur, total = int(cur or 0), int(total or 0)
    if total <= 0:
        mb     = cur // (1024 * 1024)
        cycle  = mb % (w * 2)
        filled = cycle if cycle <= w else (w * 2 - cycle)
        filled = max(1, filled)
    else:
        filled = int(w * min(cur / total, 1.0))
    return "█" * filled + "░" * (w - filled)


def _size_str(cur: int, total: int) -> str:
    cur, total = int(cur or 0), int(total or 0)
    if total:
        return f"{format_size(cur)} / {format_size(total)}"
    return f"{format_size(cur)} / ?"


def _eta_str(cur: int, total: int, speed: float) -> str:
    cur, total = int(cur or 0), int(total or 0)
    if total > 0 and speed > 0:
        return format_eta((total - cur) / speed)
    return "—"


def _clean_filename(name: str) -> str:
    import re
    name = re.sub(r'_\d+_manifest$', '', name)
    name = re.sub(r'_manifest$', '', name)
    return name.strip() or name


# ── Live emoji cycles (rotate on each card edit to simulate animation) ─────────

# Each list = frames; pick frame by (time // interval) % len
_DL_FRAMES   = ["📥", "⬇️", "📩", "⬇️"]          # downloading
_UL_FRAMES   = ["📤", "⬆️", "📨", "⬆️"]          # uploading
_FETCH_FRAMES= ["🔗", "🌐", "📡", "🌐"]          # remote fetch
_ZIP_DL_FRAMES=["📦", "📥", "🗂️", "📥"]          # zip downloading
_ZIP_UL_FRAMES=["🗜", "📤", "🗜", "📤"]          # zip uploading
_CMP_FRAMES  = ["🗜", "⚙️", "🔧", "⚙️"]          # compressing
_SPIN        = ["🌑","🌒","🌓","🌔","🌕","🌖","🌗","🌘"]  # spinner (speed indicator)


def _live(frames: list) -> str:
    """Pick current frame based on wall clock (changes every 0.5s)."""
    idx = int(time.time() * 2) % len(frames)
    return frames[idx]


def _spin_icon(speed: float) -> str:
    """Moon spinner that rotates faster with higher speed."""
    if speed <= 0:
        return "🌑"
    # one full rotation per (8 / speed_mb) seconds — faster = more rotations
    speed_mb = max(speed / (1024 * 1024), 0.01)
    idx = int(time.time() * speed_mb * 2) % len(_SPIN)
    return _SPIN[idx]


# ── Universal Progress Card ────────────────────────────────────────────────────

def progress_card(
    phase_frames: list,       # list of emoji frames for the phase icon
    phase_label: str,         # bold label text e.g. "Downloading from Telegram"
    filename: str,
    cur: int,
    total: int,
    speed: float,
    elapsed: float,
    *,
    file_num: Optional[int] = None,
    total_files: Optional[int] = None,
    extra: str = "",
) -> str:
    filename  = _clean_filename(filename)
    icon      = get_file_icon(filename)
    pct       = _pct(cur, total)
    phase_ico = _live(phase_frames)
    counter   = f"│ 🗂 {file_num} / {total_files}\n" if file_num and total_files else ""
    extra_ln  = f"│ {extra}\n" if extra else ""

    if speed > 0:
        spin    = _spin_icon(speed)
        stat_ln = f"│ {spin} {format_speed(speed)}   ⏱ {_eta_str(cur, total, speed)}\n"
    else:
        stat_ln = ""

    return (
        f"{phase_ico} <b>{phase_label}</b>\n"
        f"┌─────────────────────────\n"
        f"│ {icon} <b>{_esc(filename[:36])}</b>\n"
        f"{counter}"
        f"│ <code>{_bar(cur, total)}</code>  <b>{pct}</b>\n"
        f"│ 📦 {_size_str(cur, total)}\n"
        f"{stat_ln}"
        f"{extra_ln}"
        f"└─────────────────────────"
    )


# ── Convenience wrappers ───────────────────────────────────────────────────────

def download_progress_card(
    filename: str, cur: int, total: int, speed: float, elapsed: float,
    file_num: Optional[int] = None, total_files: Optional[int] = None,
) -> str:
    return progress_card(
        _DL_FRAMES, "Downloading from Telegram",
        filename, cur, total, speed, elapsed,
        file_num=file_num, total_files=total_files,
    )


def upload_progress_card(
    filename: str, cur: int, total: int, speed: float, elapsed: float,
    phase: str = "Uploading to VikingFile",
) -> str:
    return progress_card(
        _UL_FRAMES, phase,
        filename, cur, total, speed, elapsed,
    )


def compress_progress_card(filename: str, cur: int, total: int, level: int) -> str:
    done = cur >= total > 0
    label = "Compression Complete!" if done else "Compressing…"
    return progress_card(
        _CMP_FRAMES, label,
        filename, cur, total, 0, 0,
        extra=f"🔧 Level {level}",
    )


def zip_progress_card(
    current_file: str, file_num: int, total_files: int,
    cur: int, total: int, speed: float, elapsed: float,
    phase: str = "Downloading",
) -> str:
    if "Download" in phase:
        frames, label = _ZIP_DL_FRAMES, f"ZIP · Downloading  ({file_num}/{total_files})"
    else:
        frames, label = _ZIP_UL_FRAMES, "ZIP · Uploading"
    return progress_card(
        frames, label,
        current_file, cur, total, speed, elapsed,
        file_num=file_num, total_files=total_files,
    )


def remote_progress_card(filename: str, cur: int, total: int, speed: float, pct_str: str) -> str:
    extra = f"🌐 VikingFile: {pct_str}" if pct_str else ""
    return progress_card(
        _FETCH_FRAMES, "Remote Fetch",
        filename, cur, total, speed, 0,
        extra=extra,
    )


# ── Result Cards ───────────────────────────────────────────────────────────────

def success_card(filename: str, size, url: str, file_hash: str, user_hash: str = "") -> str:
    filename = _clean_filename(filename)
    icon     = get_file_icon(filename)
    if user_hash:
        hash_line = "\n│ 👤 <i>Saved to your account</i>"
    elif file_hash:
        hash_line = f"\n│ 🔑 <code>{file_hash}</code>  <i>(anonymous)</i>"
    else:
        hash_line = ""
    link_block = (
        f"\n\n🔗 <b>Your Download Link</b>\n"
        f"<blockquote expandable>{url}</blockquote>"
    ) if url else ""
    return (
        f"✅ <b>Upload Complete!</b>\n"
        f"┌─────────────────────────\n"
        f"│ {icon} <b>{_esc(filename)}</b>\n"
        f"│ 📦 {format_size(size)}"
        f"{hash_line}\n"
        f"└─────────────────────────"
        f"{link_block}\n"
        f"\n<i>via @NXT_HUB</i>"
    )


def zip_success_card(
    filename: str, size, url: str, file_hash: str,
    file_count: int, password_protected: bool = False, user_hash: str = "",
) -> str:
    lock = "│ 🔒 Password protected\n" if password_protected else ""
    if user_hash:
        hash_line = "\n│ 👤 <i>Saved to your account</i>"
    elif file_hash:
        hash_line = f"\n│ 🔑 <code>{file_hash}</code>  <i>(anonymous)</i>"
    else:
        hash_line = ""
    link_block = (
        f"\n\n🔗 <b>Your Download Link</b>\n"
        f"<blockquote expandable>{url}</blockquote>"
    ) if url else ""
    return (
        f"✅ <b>ZIP Complete!</b>\n"
        f"┌─────────────────────────\n"
        f"│ 🗜 <b>{_esc(filename)}</b>\n"
        f"│ 📦 {format_size(size)}  ·  {file_count} files\n"
        f"{lock}"
        f"{hash_line}\n"
        f"└─────────────────────────"
        f"{link_block}\n"
        f"\n<i>via @NXT_HUB</i>"
    )


def file_list_item(filename: str, size, downloads: int, created: str, file_hash: str) -> str:
    icon     = get_file_icon(filename)
    url      = f"https://vikingfile.com/f/{file_hash}" if file_hash else ""
    open_lnk = f'  <a href="{url}">↗ Open</a>' if url else ""
    return (
        f"{icon} <b>{_esc(filename[:32])}</b>{open_lnk}\n"
        f"<i>{format_size(size)}  ·  ⬇ {downloads}  ·  {created}</i>\n"
        f"<code>{file_hash}</code>"
    )


def error_card(title: str, message: str) -> str:
    return (
        f"❌ <b>{_esc(title)}</b>\n"
        f"┌─────────────────────────\n"
        f"│ ⚠️ {_esc(message)}\n"
        f"└─────────────────────────"
    )


def setup_required_card() -> str:
    return (
        f"⚙️ <b>Setup Required</b>\n"
        f"┌─────────────────────────\n"
        f"│ You need a <b>VikingFile User Hash</b>\n"
        f"│ before uploads will work.\n"
        f"│\n"
        f"│ <b>How to get your hash:</b>\n"
        f"│ 1️⃣  Go to <a href=\"https://vikingfile.com\">vikingfile.com</a>\n"
        f"│ 2️⃣  Log in / create a free account\n"
        f"│ 3️⃣  Open ⚙️ Settings → copy your <b>User Hash</b>\n"
        f"│ 4️⃣  Come back here → ⚙️ Settings → User Hash\n"
        f"│ 5️⃣  Paste it and resend your file ✅\n"
        f"└─────────────────────────"
    )
