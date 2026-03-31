import os
import asyncio
import time
import hmac
import secrets
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import octobot_trading.api as trading_api
import octobot.octobot_api as octobot_api_module

logger = logging.getLogger("ParadexDashboard")

# Session secret: separate from password, cryptographically random
_SESSION_SECRET = os.getenv("DASHBOARD_SESSION_SECRET", secrets.token_hex(32))

app = FastAPI(title="Paradex Dashboard", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=_SESSION_SECRET,
    https_only=os.getenv("RAILWAY_ENVIRONMENT") is not None,
)

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
_bot_api = None


@app.get("/health")
async def health():
    return {"status": "ok"}


def set_bot_api(bot_api):
    global _bot_api
    _bot_api = bot_api


def _get_exchange_managers():
    if _bot_api is None:
        return []
    try:
        ids = _bot_api.get_exchange_manager_ids()
        return [trading_api.get_exchange_manager_from_exchange_id(eid) for eid in ids]
    except Exception as e:
        logger.error(f"Failed to get exchange managers: {e}")
        return []


def _get_exchange_manager():
    managers = _get_exchange_managers()
    return managers[0] if managers else None


def require_auth(request: Request):
    if DASHBOARD_PASSWORD and request.session.get("authenticated") != True:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                            headers={"Location": "/login"})


# --- Auth ---

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    password = form.get("password", "")
    if hmac.compare_digest(password, DASHBOARD_PASSWORD):
        request.session["authenticated"] = True
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Wrong password"})


# --- Dashboard ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if DASHBOARD_PASSWORD and request.session.get("authenticated") != True:
        return RedirectResponse("/login")
    return templates.TemplateResponse("dashboard.html", {"request": request})


# --- API endpoints ---

@app.get("/api/status")
async def api_status(request: Request):
    if DASHBOARD_PASSWORD and request.session.get("authenticated") != True:
        raise HTTPException(401)
    em = _get_exchange_manager()
    if not em:
        return {"status": "disconnected", "exchange": None, "uptime": 0}
    try:
        uptime = time.time() - _bot_api.get_start_time() if _bot_api else 0
        return {
            "status": "running",
            "exchange": "paradex",
            "uptime": round(uptime),
            "bot_id": _bot_api.get_bot_id() if _bot_api else None,
        }
    except Exception:
        logger.exception("Error in /api/status")
        return {"status": "error", "error": "internal error"}


@app.get("/api/portfolio")
async def api_portfolio(request: Request):
    if DASHBOARD_PASSWORD and request.session.get("authenticated") != True:
        raise HTTPException(401)
    em = _get_exchange_manager()
    if not em:
        return {"portfolio": {}, "value": 0}
    try:
        portfolio = trading_api.get_portfolio(em, as_decimal=False)
        current_value = trading_api.get_current_portfolio_value(em)
        origin_value = trading_api.get_origin_portfolio_value(em)
        return {
            "portfolio": {k: {"total": v.get("total", 0), "available": v.get("free", 0)}
                          for k, v in portfolio.items() if v.get("total", 0) > 0},
            "value": float(current_value) if current_value else 0,
            "origin_value": float(origin_value) if origin_value else 0,
        }
    except Exception:
        logger.exception("Error in /api/portfolio")
        return {"portfolio": {}, "value": 0, "error": "internal error"}


@app.get("/api/positions")
async def api_positions(request: Request):
    if DASHBOARD_PASSWORD and request.session.get("authenticated") != True:
        raise HTTPException(401)
    em = _get_exchange_manager()
    if not em:
        return {"positions": []}
    try:
        positions = trading_api.get_positions(em)
        result = []
        for p in positions:
            result.append({
                "symbol": str(getattr(p, "symbol", "")),
                "side": str(getattr(p, "side", "")),
                "size": float(getattr(p, "size", 0)),
                "entry_price": float(getattr(p, "entry_price", 0)),
                "mark_price": float(getattr(p, "mark_price", 0)),
                "liquidation_price": float(getattr(p, "liquidation_price", 0)),
                "unrealized_pnl": float(getattr(p, "unrealized_pnl", 0)),
                "leverage": float(getattr(p, "leverage", 1)),
            })
        return {"positions": result}
    except Exception:
        logger.exception("Error in /api/positions")
        return {"positions": [], "error": "internal error"}


@app.get("/api/orders")
async def api_orders(request: Request):
    if DASHBOARD_PASSWORD and request.session.get("authenticated") != True:
        raise HTTPException(401)
    em = _get_exchange_manager()
    if not em:
        return {"orders": []}
    try:
        orders = trading_api.get_open_orders(em)
        result = []
        for o in orders:
            result.append({
                "id": str(getattr(o, "order_id", "")),
                "symbol": str(getattr(o, "symbol", "")),
                "side": str(getattr(o, "side", "")),
                "type": str(getattr(o, "order_type", "")),
                "price": float(getattr(o, "origin_price", 0)),
                "amount": float(getattr(o, "origin_quantity", 0)),
                "status": str(getattr(o, "status", "")),
            })
        return {"orders": result}
    except Exception:
        logger.exception("Error in /api/orders")
        return {"orders": [], "error": "internal error"}


@app.get("/api/pnl")
async def api_pnl(request: Request):
    if DASHBOARD_PASSWORD and request.session.get("authenticated") != True:
        raise HTTPException(401)
    em = _get_exchange_manager()
    if not em:
        return {"pnl": [], "total_fees": {}, "win_rate": 0}
    try:
        pnl_history = trading_api.get_completed_pnl_history(em)
        total_fees = trading_api.get_total_paid_trading_fees(em)
        profitability = trading_api.get_profitability_stats(em)
        result = []
        for p in (pnl_history or [])[-50:]:
            result.append({
                "symbol": str(getattr(p, "symbol", "")),
                "pnl": float(getattr(p, "pnl", 0)),
                "timestamp": float(getattr(p, "close_timestamp", 0)),
            })
        return {
            "pnl": result,
            "total_fees": {k: float(v) for k, v in (total_fees or {}).items()},
            "profitability": {
                "value": float(profitability[0]) if profitability[0] else 0,
                "percent": float(profitability[1]) if profitability[1] else 0,
                "market_percent": float(profitability[3]) if profitability[3] else 0,
            } if profitability else {},
        }
    except Exception:
        logger.exception("Error in /api/pnl")
        return {"pnl": [], "error": "internal error"}


@app.get("/api/trades")
async def api_trades(request: Request):
    if DASHBOARD_PASSWORD and request.session.get("authenticated") != True:
        raise HTTPException(401)
    em = _get_exchange_manager()
    if not em:
        return {"trades": []}
    try:
        trades = trading_api.get_trade_history(em)
        result = []
        for t in (trades or [])[-50:]:
            result.append({
                "symbol": str(getattr(t, "symbol", "")),
                "side": str(getattr(t, "side", "")),
                "price": float(getattr(t, "executed_price", 0)),
                "amount": float(getattr(t, "executed_quantity", 0)),
                "fee": float(getattr(t, "fee", {}).get("cost", 0)) if isinstance(getattr(t, "fee", None), dict) else 0,
                "timestamp": float(getattr(t, "executed_time", 0)),
            })
        return {"trades": result}
    except Exception:
        logger.exception("Error in /api/trades")
        return {"trades": [], "error": "internal error"}


# --- WebSocket for live updates ---

@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    # Authenticate WebSocket via session cookie
    if DASHBOARD_PASSWORD:
        session = websocket.cookies.get("session")
        if not session:
            await websocket.close(code=4001, reason="Unauthorized")
            return
    await websocket.accept()
    try:
        while True:
            em = _get_exchange_manager()
            data = {"status": "disconnected"}
            if em:
                try:
                    positions = trading_api.get_positions(em)
                    orders = trading_api.get_open_orders(em)
                    portfolio = trading_api.get_portfolio(em, as_decimal=False)
                    current_value = trading_api.get_current_portfolio_value(em)
                    data = {
                        "status": "running",
                        "portfolio_value": float(current_value) if current_value else 0,
                        "positions_count": len(positions),
                        "orders_count": len(orders),
                        "positions": [
                            {
                                "symbol": str(getattr(p, "symbol", "")),
                                "size": float(getattr(p, "size", 0)),
                                "unrealized_pnl": float(getattr(p, "unrealized_pnl", 0)),
                            }
                            for p in positions
                        ],
                    }
                except Exception:
                    logger.exception("Error in WebSocket data fetch")
                    data = {"status": "error", "error": "internal error"}
            await websocket.send_json(data)
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        pass
