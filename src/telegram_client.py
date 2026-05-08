from __future__ import annotations

from typing import Any

import httpx


class TelegramClient:
    def __init__(self, *, api_base: str, bot_token: str) -> None:
        self.api_base = api_base.rstrip("/")
        self.bot_token = bot_token
        self.base_url = f"{self.api_base}/bot{self.bot_token}"

    async def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{self.base_url}/{method}", json=payload)
            response.raise_for_status()
            body = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram API error for {method}: {body}")
        return body["result"]

    async def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("sendMessage", payload)

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("editMessageText", payload)

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None, show_alert: bool = False) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            payload["text"] = text
        await self.call("answerCallbackQuery", payload)

    async def set_webhook(self, url: str, secret_token: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"url": url}
        if secret_token:
            payload["secret_token"] = secret_token
        return await self.call("setWebhook", payload)

    async def get_me(self) -> dict[str, Any]:
        return await self.call("getMe", {})
