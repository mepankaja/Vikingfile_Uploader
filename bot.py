import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramUnauthorizedError

from config import BOT_TOKEN
from utils.db import init_db
from utils.tg_downloader import get_pyro_client, stop_pyro_client
from handlers import start, upload, zip_handler, settings, my_files, broadcast
from middlewares.throttling import ThrottlingMiddleware
from middlewares.subscription import SubscriptionMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.critical("❌ BOT_TOKEN is not set in config.py!")
        sys.exit(1)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Verify token works before doing anything else
    try:
        me = await bot.get_me()
        logger.info(f"✅ Bot authenticated: @{me.username} (id={me.id})")
    except TelegramUnauthorizedError:
        logger.critical(
            "❌ BOT_TOKEN is invalid or revoked!\n"
            "   → Go to @BotFather → /mybots → your bot → API Token → Revoke\n"
            "   → Paste the new token into config.py\n"
            "   → Rebuild and redeploy"
        )
        await bot.session.close()
        sys.exit(1)
    except Exception as e:
        logger.critical(f"❌ Failed to connect to Telegram: {e}")
        await bot.session.close()
        sys.exit(1)

    try:
        await init_db()
        # Pre-connect Pyrogram so the first large download is instant
        try:
            await get_pyro_client()
        except Exception as e:
            logger.warning(f"Pyrogram pre-connect skipped: {e}")
    except Exception as e:
        logger.critical(f"❌ MongoDB connection failed: {e}")
        logger.critical("Set MONGO_URI environment variable with your actual connection string")
        raise
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.message.middleware(ThrottlingMiddleware())
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    # Router order matters — zip must come before upload for state handling
    dp.include_router(broadcast.router)     # hidden admin commands — checked first, silent for non-admins
    dp.include_router(start.router)
    dp.include_router(zip_handler.router)   # zip states take priority
    dp.include_router(settings.router)      # settings states before upload catch-all
    dp.include_router(my_files.router)      # files_path state before upload catch-all
    dp.include_router(upload.router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.warning(f"Could not delete webhook: {e}")

    # Register bot commands
    try:
        from aiogram.types import BotCommand, BotCommandScopeDefault
        commands = [
            BotCommand(command="start",    description="🏠 Main menu"),
            BotCommand(command="help",     description="📖 Help & guide"),
            BotCommand(command="zip",      description="🗜️ Start ZIP builder"),
            BotCommand(command="done",     description="✅ Finish & build ZIP"),
            BotCommand(command="myfiles",  description="📁 View your uploaded files"),
            BotCommand(command="settings", description="⚙️ Settings"),
            BotCommand(command="cancel",   description="❌ Cancel current operation"),
        ]
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        logger.info("✅ Commands registered")
    except Exception as e:
        logger.warning(f"Could not set commands: {e}")

    logger.info("🚀 VikingFile Bot is running!")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await stop_pyro_client()
        await bot.session.close()
        logger.info("👋 Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
