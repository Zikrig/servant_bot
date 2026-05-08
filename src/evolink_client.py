from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx


class EvolinkClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        primary_model: str,
        fallback_model: str | None,
        timeout_sec: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.timeout = timeout_sec
        self.logger = logging.getLogger(__name__)

    async def _chat_completion(self, model: str, system_prompt: str, user_text: str) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.8,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        text = ""
        choices = data.get("choices", [])
        if choices:
            text = choices[0].get("message", {}).get("content", "").strip()
        return {
            "text": text,
            "usage": data.get("usage"),
            "model": data.get("model", model),
        }

    async def list_models(self) -> list[str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/models", headers=headers)
            response.raise_for_status()
            data = response.json()
        models = data.get("data", [])
        return [item.get("id", "") for item in models if item.get("id")]

    async def validate_configured_models(self) -> None:
        configured = [self.primary_model]
        if self.fallback_model:
            configured.append(self.fallback_model)

        available = await self.list_models()
        missing = [model for model in configured if model not in available]
        if missing:
            sample = ", ".join(available[:12]) if available else "(empty)"
            raise RuntimeError(
                "Configured Evolink model IDs not found: "
                f"{', '.join(missing)}. Available sample: {sample}"
            )

    async def generate(self, *, system_prompt: str, user_text: str) -> dict[str, Any]:
        attempts: list[tuple[str, int]] = [(self.primary_model, 2)]
        if self.fallback_model and self.fallback_model != self.primary_model:
            attempts.append((self.fallback_model, 1))

        last_error: Exception | None = None
        for model, retries in attempts:
            for attempt in range(1, retries + 1):
                try:
                    return await self._chat_completion(model, system_prompt, user_text)
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    self.logger.warning(
                        "Evolink request failed (model=%s, attempt=%s/%s): %s",
                        model,
                        attempt,
                        retries,
                        exc,
                    )
                    if attempt < retries:
                        await asyncio.sleep(0.7 * attempt)
        raise RuntimeError(f"Evolink request failed after retries: {last_error}") from last_error
