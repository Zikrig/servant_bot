from __future__ import annotations

import logging

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from src.bot_service import BotService
from src.config import EVOLINK_BASE_URL, TELEGRAM_API_BASE, settings
from src.db import init_db
from src.evolink_client import EvolinkClient
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
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
]

storage = Storage(settings.db_path)
telegram = TelegramClient(api_base=TELEGRAM_API_BASE, bot_token=settings.telegram_bot_token)
scenarios = ScenarioManager(
    storage,
    ValidationLimits(
        max_scenarios_per_user=settings.max_scenarios_per_user,
        max_title_len=settings.max_scenario_title_len,
        max_prompt_len=settings.max_scenario_prompt_len,
    ),
)
panel = PanelRenderer()
evolink = EvolinkClient(
    base_url=EVOLINK_BASE_URL,
    api_key=settings.evolink_api_key,
    primary_model=settings.evolink_model_primary,
    fallback_model=settings.evolink_model_fallback,
    timeout_sec=settings.evolink_request_timeout_sec,
)
bot = BotService(
    storage=storage,
    scenarios=scenarios,
    panel=panel,
    evolink=evolink,
    telegram=telegram,
    bot_username=settings.telegram_bot_username,
)

app = FastAPI(title="Servant Bot", version="0.1.0")


@app.on_event("startup")
async def startup() -> None:
    await init_db(settings.db_path)
    me = await telegram.get_me()
    username = me.get("username")
    if not username:
        raise RuntimeError("Telegram getMe returned no username.")
    bot.set_bot_username(username)
    logger.info("Bot identity loaded from Telegram: @%s", username)

    try:
        await evolink.validate_configured_models()
        logger.info(
            "Evolink models validated: primary=%s fallback=%s",
            settings.evolink_model_primary,
            settings.evolink_model_fallback,
        )
    except Exception as exc:  # noqa: BLE001
        if settings.evolink_strict_model_validation:
            raise
        logger.warning("Evolink model validation skipped due to error: %s", exc)

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
        elif "business_message" in update:
            await bot.handle_message(update["business_message"], source="business_message")
        elif "edited_business_message" in update:
            # Edited updates are still useful for diagnostics in business chats.
            await bot.handle_message(update["edited_business_message"], source="edited_business_message")
        else:
            logger.info("Unhandled update type: update_id=%s keys=%s", update_id, update_keys)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to process update: %s", exc)

    return JSONResponse({"ok": True})
