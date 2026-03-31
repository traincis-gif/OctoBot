"""
Paradex Launcher — starts Dashboard first (for healthcheck),
then OctoBot engine + Telegram bot.
"""
import os
import sys
import asyncio
import threading
import logging
import time

logger = logging.getLogger("ParadexLauncher")


def _start_dashboard(port: int):
    """Run FastAPI dashboard in a background thread."""
    import uvicorn
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
    return thread


async def _inject_services(bot):
    """Wait for exchange to be ready, then inject API into Dashboard + Telegram."""
    from octobot.octobot_api import OctoBotAPI

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
    # 1. Start dashboard FIRST — Railway healthcheck needs it immediately
    dashboard_port = int(os.getenv("PORT", "8080"))
    _start_dashboard(dashboard_port)
    logger.info(f"Dashboard listening on :{dashboard_port}, starting OctoBot...")

    # 2. Patch OctoBot to inject services after init
    try:
        from octobot import commands as octobot_commands
        original_start_bot = octobot_commands.start_bot

        async def patched_start_bot(bot, bot_logger, catch=False):
            await original_start_bot(bot, bot_logger, catch=catch)
            asyncio.ensure_future(_inject_services(bot))

        octobot_commands.start_bot = patched_start_bot

        # 3. Run OctoBot CLI (blocks forever)
        from octobot.cli import main as octobot_main
        octobot_main()
    except Exception as e:
        logger.error(f"OctoBot failed to start: {e}")
        # Keep process alive so dashboard stays up for debugging
        logger.info("Dashboard still running for diagnostics. Check /health")
        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
