from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.bot_service import BotService
from src.config import TELEGRAM_API_BASE, settings
from src.db import init_db
from src.panel_renderer import PanelRenderer
from src.scenario_manager import ScenarioManager, ValidationLimits
from src.storage import Storage
from src.telegram_client import TelegramClient


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
WEBHOOK_ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "callback_query",
]
scheduler_task: asyncio.Task | None = None

storage = Storage(settings.db_path)
telegram = TelegramClient(api_base=TELEGRAM_API_BASE, bot_token=settings.telegram_bot_token)
scenarios = ScenarioManager(
    storage,
    ValidationLimits(
        max_scenarios_per_user=settings.max_scenarios_per_user,
        max_title_len=settings.max_scenario_title_len,
        max_reply_len=settings.max_scenario_reply_len,
    ),
)
panel = PanelRenderer()
bot = BotService(
    storage=storage,
    scenarios=scenarios,
    panel=panel,
    telegram=telegram,
    bot_username=settings.telegram_bot_username,
)

app = FastAPI(title="Servant Bot", version="0.1.0")


@app.on_event("startup")
async def startup() -> None:
    global scheduler_task
    await init_db(settings.db_path)
    me = await telegram.get_me()
    username = me.get("username")
    if not username:
        raise RuntimeError("Telegram getMe returned no username.")
    bot.set_bot_username(username)
    logger.info("Bot identity loaded from Telegram: @%s", username)

    if settings.auto_set_webhook:
        webhook_url = f"{settings.webhook_public_url.rstrip('/')}/telegram/webhook"
        try:
            result = await telegram.set_webhook(
                url=webhook_url,
                secret_token=settings.webhook_secret_token,
                allowed_updates=WEBHOOK_ALLOWED_UPDATES,
            )
            logger.info("Webhook configured: %s", result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to set webhook: %s", exc)

    scheduler_task = asyncio.create_task(bot.run_scheduler_loop(settings.scheduler_poll_seconds))


@app.on_event("shutdown")
async def shutdown() -> None:
    global scheduler_task
    if scheduler_task is not None:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        scheduler_task = None


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> JSONResponse:
    if settings.webhook_secret_token and x_telegram_bot_api_secret_token != settings.webhook_secret_token:
        raise HTTPException(status_code=401, detail="Unauthorized webhook")

    update = await request.json()
    update_id = update.get("update_id")
    update_keys = sorted([key for key in update.keys() if key != "update_id"])
    logger.info("Incoming update_id=%s keys=%s", update_id, update_keys)

    try:
        if "callback_query" in update:
            await bot.handle_callback(update["callback_query"])
        elif "message" in update:
            await bot.handle_message(update["message"], source="message")
        elif "edited_message" in update:
            await bot.handle_message(update["edited_message"], source="edited_message")
        else:
            logger.info("Unhandled update type: update_id=%s keys=%s", update_id, update_keys)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to process update: %s", exc)

    return JSONResponse({"ok": True})
