import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Pyrogram (MTProto) — for large file downloads from Telegram
# Get these at https://my.telegram.org
PYROGRAM_API_ID   = int(os.environ.get("PYROGRAM_API_ID", "0"))
PYROGRAM_API_HASH = os.environ.get("PYROGRAM_API_HASH", "YOUR_API_HASH_HERE")

VIKINGFILE_API  = "https://vikingfile.com/api"
VIKINGFILE_BASE = "https://vikingfile.com"

# MongoDB — set MONGO_URI in your environment/deployment
MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb+srv://USERNAME:PASSWORD@cluster0.mongodb.net/?appName=Cluster0"
)
MONGO_DB = os.environ.get("MONGO_DB", "nxtup")

# Temp directory for downloads
TEMP_DIR = os.environ.get("TEMP_DIR", "temp")

# Telegram Bot API hard limit for getFile
TG_BOT_MAX_SIZE = 20 * 1024 * 1024   # 20 MB

# Progress update interval (seconds)
PROGRESS_INTERVAL = 3

# NXT_HUB branding
NXT_HUB_USERNAME  = "@NXT_HUB"
NXT_HUB_LINK      = "https://t.me/NXT_HUB"

# Log channel — every upload is silently posted here (optional)
LOG_CHANNEL_ID    = int(os.environ.get("LOG_CHANNEL_ID", "0"))

# Admin user IDs (comma-separated) — allowed to use /broadcast and /stats
ADMIN_IDS_RAW = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = {int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()}
