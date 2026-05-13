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

    async def send_text_document(
        self,
        *,
        chat_id: int,
        filename: str,
        text: str,
        caption: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.base_url}/sendDocument",
                data=data,
                files={"document": (filename, text.encode("utf-8"), "text/plain")},
            )
            response.raise_for_status()
            body = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram API error for sendDocument: {body}")
        return body["result"]

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict | None = None,
        *,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
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

    async def answer_guest_query(
        self,
        *,
        guest_query_id: str,
        text: str,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        input_message_content: dict[str, Any] = {"message_text": text}
        if parse_mode:
            input_message_content["parse_mode"] = parse_mode
        payload = {
            "guest_query_id": guest_query_id,
            "result": {
                "type": "article",
                "id": f"guest-{guest_query_id}"[:64],
                "title": "Reply",
                "input_message_content": input_message_content,
            },
        }
        return await self.call("answerGuestQuery", payload)

    async def set_webhook(
        self,
        url: str,
        secret_token: str | None = None,
        *,
        allowed_updates: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"url": url}
        if secret_token:
            payload["secret_token"] = secret_token
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        return await self.call("setWebhook", payload)

    async def get_me(self) -> dict[str, Any]:
        return await self.call("getMe", {})

    async def get_chat_administrators(self, chat_id: int) -> list[dict[str, Any]]:
        return await self.call("getChatAdministrators", {"chat_id": chat_id})
