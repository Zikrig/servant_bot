from __future__ import annotations

import logging
import re

from src.evolink_client import EvolinkClient
from src.panel_renderer import PanelRenderer
from src.scenario_manager import ScenarioManager
from src.storage import Storage
from src.telegram_client import TelegramClient


class BotService:
    def __init__(
        self,
        *,
        storage: Storage,
        scenarios: ScenarioManager,
        panel: PanelRenderer,
        evolink: EvolinkClient,
        telegram: TelegramClient,
        bot_username: str | None,
    ) -> None:
        self.storage = storage
        self.scenarios = scenarios
        self.panel = panel
        self.evolink = evolink
        self.telegram = telegram
        self.bot_username = bot_username.lstrip("@").lower() if bot_username else ""
        self.logger = logging.getLogger(__name__)

    def set_bot_username(self, bot_username: str) -> None:
        self.bot_username = bot_username.lstrip("@").lower()

    def _strip_mention(self, text: str) -> str:
        if not self.bot_username:
            return text
        mention_pattern = re.compile(rf"@{re.escape(self.bot_username)}\b", re.IGNORECASE)
        cleaned = mention_pattern.sub("", text).strip()
        return " ".join(cleaned.split())

    def _is_mention_message(self, text: str) -> bool:
        if not self.bot_username:
            return False
        mention = f"@{self.bot_username}"
        return mention in text.lower()

    def _is_reply_to_bot(self, message: dict) -> bool:
        if not self.bot_username:
            return False
        reply = message.get("reply_to_message") or {}
        from_user = reply.get("from") or {}
        username = (from_user.get("username") or "").lower()
        return bool(from_user.get("is_bot")) and username == self.bot_username

    async def _render_panel(self, chat_id: int, user_id: int) -> None:
        scenario_items = await self.storage.list_scenarios(user_id)
        state = await self.storage.get_chat_state(user_id)
        text = self.panel.build_panel_text(scenario_items)
        markup = self.panel.build_panel_markup(scenario_items, state["delete_candidate_id"])
        panel_message_id = state["panel_message_id"]

        if panel_message_id:
            try:
                await self.telegram.edit_message_text(
                    chat_id=chat_id,
                    message_id=panel_message_id,
                    text=text,
                    reply_markup=markup,
                )
                return
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Failed to edit panel message, fallback to sendMessage: %s", exc)

        sent = await self.telegram.send_message(chat_id, text, reply_markup=markup)
        await self.storage.update_chat_state(user_id, panel_message_id=sent["message_id"])

    async def _handle_stateful_input(self, chat_id: int, user_id: int, text: str) -> bool:
        state = await self.storage.get_chat_state(user_id)
        if state["pending_action"] == "await_title":
            await self.storage.update_chat_state(
                user_id,
                pending_action="await_prompt",
                draft_title=text.strip(),
                delete_candidate_id=None,
            )
            await self.telegram.send_message(
                chat_id,
                "Отлично. Теперь отправьте инструкцию для сценария.\n"
                "Например: «Критикуй лаконично и по делу» "
                "или «Отвечай как древнеримский слуга».",
            )
            return True

        if state["pending_action"] == "await_prompt":
            draft_title = (state.get("draft_title") or "").strip()
            if not draft_title:
                await self.storage.update_chat_state(user_id, pending_action="await_title", draft_title=None)
                await self.telegram.send_message(chat_id, "Нужен заголовок сценария. Отправьте название еще раз.")
                return True

            try:
                await self.scenarios.add_scenario(user_id, draft_title, text.strip())
            except ValueError as exc:
                await self.telegram.send_message(chat_id, f"Не удалось создать сценарий: {exc}")
                return True

            await self.storage.update_chat_state(
                user_id,
                pending_action=None,
                draft_title=None,
                delete_candidate_id=None,
            )
            await self.telegram.send_message(chat_id, f"Сценарий «{draft_title}» добавлен.")
            await self._render_panel(chat_id, user_id)
            return True
        return False

    async def handle_start(self, chat_id: int, telegram_user_id: int) -> None:
        user = await self.storage.get_or_create_user(telegram_user_id)
        await self.storage.get_chat_state(user["id"])
        await self.telegram.send_message(
            chat_id,
            "Бот активирован. Управляйте сценариями через панель ниже.\n"
            "Одновременно может быть включен только один сценарий.",
        )
        await self._render_panel(chat_id, user["id"])

    async def handle_message(self, message: dict) -> None:
        chat = message.get("chat", {})
        chat_id = chat["id"]
        from_user = message.get("from", {})
        telegram_user_id = from_user.get("id")
        if telegram_user_id is None:
            return
        text = (message.get("text") or "").strip()
        if not text:
            return

        user = await self.storage.get_or_create_user(telegram_user_id)
        normalized_text = text.lower()

        # Handle startup/panel commands before Guest-mode mention gating.
        if normalized_text in {"/start", "/start@" + self.bot_username}:
            await self.handle_start(chat_id, telegram_user_id)
            return
        if normalized_text in {"/panel", "/panel@" + self.bot_username}:
            await self._render_panel(chat_id, user["id"])
            return

        # Guest-only mode: react only to explicit mention or reply to bot message.
        is_mention = self._is_mention_message(text)
        is_reply_to_bot = self._is_reply_to_bot(message)
        if not is_mention and not is_reply_to_bot:
            return

        consumed = await self._handle_stateful_input(chat_id, user["id"], text)
        if consumed:
            return

        cleaned_text = self._strip_mention(text) if is_mention else text
        normalized = cleaned_text.strip().lower()
        if normalized in {"panel", "/panel"}:
            await self._render_panel(chat_id, user["id"])
            return
        if normalized in {"cancel", "/cancel"}:
            await self.storage.update_chat_state(
                user["id"],
                pending_action=None,
                draft_title=None,
                delete_candidate_id=None,
            )
            await self.telegram.send_message(chat_id, "Текущее действие отменено.")
            await self._render_panel(chat_id, user["id"])
            return

        if not cleaned_text:
            await self.telegram.send_message(
                chat_id,
                "Опишите запрос рядом с упоминанием бота, например:\n"
                f"@{self.bot_username} панель\n"
                f"@{self.bot_username} критикуй мой текст",
            )
            return

        enabled = await self.storage.get_enabled_scenario(user["id"])
        if not enabled:
            await self.telegram.send_message(
                chat_id,
                "Нет активного сценария для вашего профиля. "
                "Сначала активируйте сценарий через управляющий интерфейс.",
            )
            return

        try:
            result = await self.evolink.generate(system_prompt=enabled["system_prompt"], user_text=cleaned_text)
            answer = result["text"] or "Не удалось сгенерировать ответ."
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("LLM generation failed: %s", exc)
            answer = "Сервис модели временно недоступен. Попробуйте еще раз."
        await self.telegram.send_message(chat_id, answer)

    async def handle_callback(self, callback_query: dict) -> None:
        callback_id = callback_query["id"]
        data = callback_query.get("data", "")
        message = callback_query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        from_user = callback_query.get("from", {})
        telegram_user_id = from_user.get("id")
        if chat_id is None or telegram_user_id is None:
            return
        user = await self.storage.get_or_create_user(telegram_user_id)
        user_id = user["id"]

        # Telegram clients show a spinner until callback is answered.
        await self.telegram.answer_callback_query(callback_id)

        if data == "panel:add":
            await self.storage.update_chat_state(
                user_id,
                pending_action="await_title",
                draft_title=None,
                delete_candidate_id=None,
            )
            await self.telegram.send_message(chat_id, "Введите название нового сценария.")
            await self._render_panel(chat_id, user_id)
            return

        if data == "panel:refresh":
            await self.storage.update_chat_state(user_id, delete_candidate_id=None)
            await self._render_panel(chat_id, user_id)
            return

        if data == "sc:deln":
            await self.storage.update_chat_state(user_id, delete_candidate_id=None)
            await self._render_panel(chat_id, user_id)
            return

        if data.startswith("sc:toggle:"):
            try:
                scenario_id = int(data.split(":")[-1])
            except ValueError:
                await self.telegram.send_message(chat_id, "Некорректный идентификатор сценария.")
                return
            changed = await self.scenarios.toggle_scenario(user_id, scenario_id)
            if not changed:
                await self.telegram.send_message(chat_id, "Сценарий не найден.")
            await self.storage.update_chat_state(user_id, delete_candidate_id=None)
            await self._render_panel(chat_id, user_id)
            return

        if data.startswith("sc:delask:"):
            try:
                scenario_id = int(data.split(":")[-1])
            except ValueError:
                await self.telegram.send_message(chat_id, "Некорректный идентификатор сценария.")
                return
            await self.storage.update_chat_state(user_id, delete_candidate_id=scenario_id)
            await self._render_panel(chat_id, user_id)
            return

        if data.startswith("sc:dely:"):
            try:
                scenario_id = int(data.split(":")[-1])
            except ValueError:
                await self.telegram.send_message(chat_id, "Некорректный идентификатор сценария.")
                return
            deleted = await self.scenarios.delete_scenario(user_id, scenario_id)
            await self.storage.update_chat_state(user_id, delete_candidate_id=None)
            if deleted:
                await self.telegram.send_message(chat_id, "Сценарий удален.")
            else:
                await self.telegram.send_message(chat_id, "Сценарий уже удален или не найден.")
            await self._render_panel(chat_id, user_id)
