"""
Paradex Launcher — starts OctoBot engine + Dashboard + Telegram bot
in a single process.
"""
import os
import sys
import asyncio
import threading
import logging

import uvicorn

logger = logging.getLogger("ParadexLauncher")


def _start_dashboard_thread(port: int):
    """Run FastAPI dashboard in a background thread."""
    config = uvicorn.Config(
        "paradex_dashboard.app:app",
        host="0.0.0.0",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    logger.info(f"Dashboard started on port {port}")


async def _inject_services(bot):
    """Wait for exchange to be ready, then start Dashboard API + Telegram."""
    from octobot.octobot_api import OctoBotAPI

    # Wait for exchange managers to appear (max 120s)
    bot_api = None
    for _ in range(120):
        try:
            bot_api = OctoBotAPI(bot)
            ids = bot_api.get_exchange_manager_ids()
            if ids:
                break
        except Exception:
            pass
        await asyncio.sleep(1)

    if bot_api is None:
        try:
            bot_api = OctoBotAPI(bot)
        except Exception:
            logger.error("Could not create OctoBotAPI")
            return

    # Inject into dashboard
    from paradex_dashboard.app import set_bot_api as set_dashboard_api
    set_dashboard_api(bot_api)
    logger.info("Bot API injected into Dashboard")

    # Start Telegram bot
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        try:
            from paradex_telegram.bot import set_bot_api as set_telegram_api, start_telegram_bot
            set_telegram_api(bot_api)
            await start_telegram_bot()
        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {e}")


def main():
    # Start dashboard server in background thread
    dashboard_port = int(os.getenv("PORT", "8080"))
    _start_dashboard_thread(dashboard_port)

    # Patch OctoBot's start_bot to inject our services after initialization
    from octobot import commands as octobot_commands
    original_start_bot = octobot_commands.start_bot

    async def patched_start_bot(bot, bot_logger, catch=False):
        await original_start_bot(bot, bot_logger, catch=catch)
        # After bot is initialized, inject dashboard + telegram
        asyncio.ensure_future(_inject_services(bot))

    octobot_commands.start_bot = patched_start_bot

    # Run OctoBot CLI (blocks forever)
    from octobot.cli import main as octobot_main
    octobot_main()


if __name__ == "__main__":
    main()
