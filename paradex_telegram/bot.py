import os
import asyncio
import time
import logging
from decimal import Decimal

from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters
)

import octobot_trading.api as trading_api
import octobot.octobot_api as octobot_api_module

logger = logging.getLogger("ParadexTelegramBot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

_bot_api = None
_application = None


def set_bot_api(bot_api):
    global _bot_api
    _bot_api = bot_api


def _get_exchange_manager():
    if _bot_api is None:
        return None
    try:
        ids = _bot_api.get_exchange_manager_ids()
        if ids:
            return trading_api.get_exchange_manager_from_exchange_id(ids[0])
    except Exception as e:
        logger.error(f"Failed to get exchange manager: {e}")
    return None


def _is_authorized(update: Update) -> bool:
    if not TELEGRAM_CHAT_ID:
        return True
    return str(update.effective_chat.id) == str(TELEGRAM_CHAT_ID)


def fmt(n, d=2):
    try:
        return f"{float(n):,.{d}f}"
    except (TypeError, ValueError):
        return "-"


def fmt_uptime(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m"


# --- Commands ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    em = _get_exchange_manager()
    if not em:
        await update.message.reply_text("Bot is starting up... Try again in a moment.")
        return
    uptime = time.time() - _bot_api.get_start_time() if _bot_api else 0
    text = (
        "Paradex Trading Bot\n"
        f"Status: Running\n"
        f"Exchange: Paradex (futures)\n"
        f"Uptime: {fmt_uptime(uptime)}\n\n"
        "Commands:\n"
        "/balance - Portfolio balance\n"
        "/positions - Open positions\n"
        "/orders - Active orders\n"
        "/pnl - Profit & Loss\n"
        "/trades - Recent trades\n"
        "/grid - Grid parameters\n"
        "/risk N - Set risk level (0-1)\n"
        "/pause - Pause trading\n"
        "/resume - Resume trading\n"
    )
    await update.message.reply_text(text)


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    em = _get_exchange_manager()
    if not em:
        await update.message.reply_text("Not connected to exchange.")
        return
    try:
        portfolio = trading_api.get_portfolio(em, as_decimal=False)
        current_value = trading_api.get_current_portfolio_value(em)
        origin_value = trading_api.get_origin_portfolio_value(em)
        lines = ["Portfolio:\n"]
        for currency, amounts in portfolio.items():
            total = amounts.get("total", 0)
            if total > 0:
                free = amounts.get("free", 0)
                lines.append(f"  {currency}: {fmt(total, 4)} (avail: {fmt(free, 4)})")
        lines.append(f"\nValue: ${fmt(current_value)}")
        lines.append(f"Initial: ${fmt(origin_value)}")
        if current_value and origin_value:
            pct = ((float(current_value) / float(origin_value)) - 1) * 100
            lines.append(f"Change: {'+' if pct >= 0 else ''}{fmt(pct)}%")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    em = _get_exchange_manager()
    if not em:
        await update.message.reply_text("Not connected to exchange.")
        return
    try:
        positions = trading_api.get_positions(em)
        if not positions:
            await update.message.reply_text("No open positions.")
            return
        lines = ["Open Positions:\n"]
        for p in positions:
            size = float(getattr(p, "size", 0))
            if size == 0:
                continue
            symbol = getattr(p, "symbol", "?")
            side = "LONG" if size > 0 else "SHORT"
            entry = float(getattr(p, "entry_price", 0))
            mark = float(getattr(p, "mark_price", 0))
            liq = float(getattr(p, "liquidation_price", 0))
            upnl = float(getattr(p, "unrealized_pnl", 0))
            lev = float(getattr(p, "leverage", 1))
            emoji = "+" if upnl >= 0 else ""
            lines.append(
                f"{symbol} {side} {fmt(abs(size), 4)}\n"
                f"  Entry: {fmt(entry)} | Mark: {fmt(mark)}\n"
                f"  Liq: {fmt(liq)} | Lev: {fmt(lev, 0)}x\n"
                f"  uPnL: {emoji}${fmt(upnl)}\n"
            )
        if len(lines) == 1:
            await update.message.reply_text("No open positions (all zero).")
            return
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    em = _get_exchange_manager()
    if not em:
        await update.message.reply_text("Not connected to exchange.")
        return
    try:
        orders = trading_api.get_open_orders(em)
        if not orders:
            await update.message.reply_text("No active orders.")
            return
        lines = [f"Active Orders ({len(orders)}):\n"]
        for o in orders[:30]:
            symbol = getattr(o, "symbol", "?")
            side = str(getattr(o, "side", "?"))
            otype = str(getattr(o, "order_type", "?"))
            price = float(getattr(o, "origin_price", 0))
            amount = float(getattr(o, "origin_quantity", 0))
            lines.append(f"  {symbol} {side} {otype} @ {fmt(price)} x {fmt(amount, 4)}")
        if len(orders) > 30:
            lines.append(f"  ... and {len(orders) - 30} more")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    em = _get_exchange_manager()
    if not em:
        await update.message.reply_text("Not connected to exchange.")
        return
    try:
        profitability = trading_api.get_profitability_stats(em)
        total_fees = trading_api.get_total_paid_trading_fees(em)
        lines = ["Profit & Loss:\n"]
        if profitability:
            pct = float(profitability[1]) if profitability[1] else 0
            val = float(profitability[0]) if profitability[0] else 0
            mkt = float(profitability[3]) if profitability[3] else 0
            lines.append(f"  PnL: {'+' if val >= 0 else ''}${fmt(val)} ({'+' if pct >= 0 else ''}{fmt(pct)}%)")
            lines.append(f"  Market: {'+' if mkt >= 0 else ''}{fmt(mkt)}%")
        if total_fees:
            lines.append("\nFees paid:")
            for curr, amount in total_fees.items():
                lines.append(f"  {curr}: {fmt(float(amount), 6)}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    em = _get_exchange_manager()
    if not em:
        await update.message.reply_text("Not connected to exchange.")
        return
    try:
        trades = trading_api.get_trade_history(em)
        if not trades:
            await update.message.reply_text("No trades yet.")
            return
        recent = trades[-10:]
        lines = [f"Recent Trades (last {len(recent)}):\n"]
        for t in reversed(recent):
            symbol = getattr(t, "symbol", "?")
            side = str(getattr(t, "side", "?"))
            price = float(getattr(t, "executed_price", 0))
            amount = float(getattr(t, "executed_quantity", 0))
            lines.append(f"  {symbol} {side} @ {fmt(price)} x {fmt(amount, 4)}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_grid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    em = _get_exchange_manager()
    if not em:
        await update.message.reply_text("Not connected to exchange.")
        return
    try:
        orders = trading_api.get_open_orders(em)
        buy_orders = [o for o in orders if "buy" in str(getattr(o, "side", "")).lower()]
        sell_orders = [o for o in orders if "sell" in str(getattr(o, "side", "")).lower()]
        lines = [
            "Grid Status:\n",
            f"  Total orders: {len(orders)}",
            f"  Buy orders: {len(buy_orders)}",
            f"  Sell orders: {len(sell_orders)}",
        ]
        if buy_orders:
            prices = [float(getattr(o, "origin_price", 0)) for o in buy_orders]
            lines.append(f"  Buy range: {fmt(min(prices))} - {fmt(max(prices))}")
        if sell_orders:
            prices = [float(getattr(o, "origin_price", 0)) for o in sell_orders]
            lines.append(f"  Sell range: {fmt(min(prices))} - {fmt(max(prices))}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /risk 0.5 (value 0.0 to 1.0)")
        return
    try:
        risk = float(context.args[0])
        if not 0 <= risk <= 1:
            await update.message.reply_text("Risk must be between 0.0 and 1.0")
            return
        config = _bot_api.get_edited_config(dict_only=True)
        config["trading"]["risk"] = risk
        await update.message.reply_text(f"Risk level set to {risk}")
    except ValueError:
        await update.message.reply_text("Invalid number. Usage: /risk 0.5")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    try:
        await _bot_api.stop_all_trading_modes_and_pause_traders()
        await update.message.reply_text("Trading PAUSED. Use /resume to restart.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await update.message.reply_text(
        "To resume trading, restart the bot from Railway dashboard.\n"
        "(Hot resume not supported — requires re-initialization)"
    )


# --- Alert sender ---

async def send_alert(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not _application:
        return
    try:
        await _application.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")


# --- Start bot ---

async def start_telegram_bot():
    global _application
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set, Telegram bot disabled")
        return

    _application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    _application.add_handler(CommandHandler("start", cmd_start))
    _application.add_handler(CommandHandler("balance", cmd_balance))
    _application.add_handler(CommandHandler("positions", cmd_positions))
    _application.add_handler(CommandHandler("orders", cmd_orders))
    _application.add_handler(CommandHandler("pnl", cmd_pnl))
    _application.add_handler(CommandHandler("trades", cmd_trades))
    _application.add_handler(CommandHandler("grid", cmd_grid))
    _application.add_handler(CommandHandler("risk", cmd_risk))
    _application.add_handler(CommandHandler("pause", cmd_pause))
    _application.add_handler(CommandHandler("resume", cmd_resume))

    commands = [
        BotCommand("start", "Bot status and help"),
        BotCommand("balance", "Portfolio balance"),
        BotCommand("positions", "Open positions"),
        BotCommand("orders", "Active orders"),
        BotCommand("pnl", "Profit & Loss"),
        BotCommand("trades", "Recent trades"),
        BotCommand("grid", "Grid parameters"),
        BotCommand("risk", "Set risk level (0-1)"),
        BotCommand("pause", "Pause trading"),
        BotCommand("resume", "Resume trading"),
    ]

    await _application.initialize()
    await _application.bot.set_my_commands(commands)
    await _application.start()
    await _application.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot started")
