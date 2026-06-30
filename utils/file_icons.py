"""Maps file extensions to relevant emoji icons."""

_EXT_ICONS = {
    # Documents
    "pdf":  "📕", "doc": "📝", "docx": "📝", "odt": "📝",
    "xls":  "📊", "xlsx": "📊", "ods": "📊", "csv": "📊",
    "ppt":  "📋", "pptx": "📋", "odp": "📋",
    "txt":  "📄", "md": "📄", "rst": "📄", "rtf": "📄",
    "tex":  "📄", "log": "📄",

    # Archives
    "zip":  "🗜️", "rar": "🗜️", "7z": "🗜️", "tar": "🗜️",
    "gz":   "🗜️", "bz2": "🗜️", "xz": "🗜️", "zst": "🗜️",
    "iso":  "💿", "dmg": "💿", "img": "💿",

    # Images
    "jpg":  "🖼️", "jpeg": "🖼️", "png": "🖼️", "gif": "🎞️",
    "webp": "🖼️", "bmp": "🖼️", "tiff": "🖼️", "tif": "🖼️",
    "svg":  "🖼️", "ico": "🖼️", "heic": "🖼️", "heif": "🖼️",
    "psd":  "🎨", "ai": "🎨", "xcf": "🎨", "sketch": "🎨",
    "raw":  "📷", "cr2": "📷", "nef": "📷", "arw": "📷",

    # Video
    "mp4":  "🎬", "mkv": "🎬", "avi": "🎬", "mov": "🎬",
    "wmv":  "🎬", "flv": "🎬", "webm": "🎬", "m4v": "🎬",
    "3gp":  "🎬", "ogv": "🎬", "ts": "🎬", "m2ts": "🎬",
    "vob":  "🎬", "mpg": "🎬", "mpeg": "🎬",

    # Audio
    "mp3":  "🎵", "flac": "🎵", "wav": "🎵", "aac": "🎵",
    "ogg":  "🎵", "m4a": "🎵", "wma": "🎵", "opus": "🎵",
    "aiff": "🎵", "mid": "🎵", "midi": "🎵",

    # Code / Dev
    "py":   "🐍", "ipynb": "🐍",
    "js":   "🟨", "ts": "🟦", "jsx": "🟨", "tsx": "🟦",
    "html": "🌐", "htm": "🌐", "css": "🎨", "scss": "🎨",
    "json": "📋", "xml": "📋", "yaml": "📋", "yml": "📋",
    "toml": "📋", "ini": "📋", "cfg": "📋", "conf": "📋",
    "sql":  "🗄️", "db": "🗄️", "sqlite": "🗄️", "sqlite3": "🗄️",
    "sh":   "⚙️", "bash": "⚙️", "zsh": "⚙️", "fish": "⚙️",
    "bat":  "⚙️", "cmd": "⚙️", "ps1": "⚙️",
    "c":    "💻", "cpp": "💻", "cc": "💻", "h": "💻", "hpp": "💻",
    "java": "☕", "class": "☕", "jar": "☕",
    "go":   "🐹", "rs": "🦀", "rb": "💎", "php": "🐘",
    "swift":"🍎", "kt": "🟣", "dart": "🎯", "lua": "🌙",
    "r":    "📈", "m": "📐", "jl": "📊",
    "dockerfile": "🐳", "makefile": "🔨",

    # Executables / System
    "exe":  "🖥️", "msi": "🖥️", "apk": "📱", "ipa": "📱",
    "deb":  "🐧", "rpm": "🐧", "appimage": "🐧",
    "dll":  "⚙️", "so": "⚙️", "dylib": "⚙️",

    # Fonts
    "ttf":  "🔤", "otf": "🔤", "woff": "🔤", "woff2": "🔤",

    # eBooks
    "epub": "📚", "mobi": "📚", "azw": "📚", "azw3": "📚",

    # 3D / CAD
    "stl":  "🧊", "obj": "🧊", "fbx": "🧊", "blend": "🧊",

    # Data / ML
    "pt":   "🤖", "pth": "🤖", "onnx": "🤖", "h5": "🤖",
    "pkl":  "📦", "pickle": "📦", "npy": "📦", "npz": "📦",

    # Subtitles
    "srt":  "💬", "vtt": "💬", "ass": "💬", "sub": "💬",

    # Torrents / P2P
    "torrent": "🧲",
}

_MIME_ICONS = {
    "image":       "🖼️",
    "video":       "🎬",
    "audio":       "🎵",
    "text":        "📄",
    "application/pdf": "📕",
    "application/zip": "🗜️",
    "application/x-rar": "🗜️",
    "application/x-tar": "🗜️",
    "application/gzip": "🗜️",
    "application/json": "📋",
    "application/xml": "📋",
    "application/msword": "📝",
    "application/vnd.openxmlformats-officedocument.wordprocessingml": "📝",
    "application/vnd.ms-excel": "📊",
    "application/vnd.openxmlformats-officedocument.spreadsheetml": "📊",
    "application/vnd.ms-powerpoint": "📋",
    "application/octet-stream": "📦",
}


def get_file_icon(filename: str, mime_type: str = "") -> str:
    """Return an emoji icon for the given filename or mime type."""
    if filename:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        # Special case: files named exactly "Dockerfile", "Makefile" etc.
        basename = filename.lower()
        if basename in ("dockerfile", "makefile", "rakefile", "gemfile"):
            return _EXT_ICONS.get(basename, "📄")
        if ext in _EXT_ICONS:
            return _EXT_ICONS[ext]

    if mime_type:
        # Exact match first
        for key, icon in _MIME_ICONS.items():
            if mime_type.startswith(key):
                return icon

    return "📄"  # default
