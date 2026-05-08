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

    @staticmethod
    def _sender_label(user: dict) -> str:
        username = (user.get("username") or "").strip()
        if username:
            return f"@{username}"
        full_name = " ".join(part for part in [(user.get("first_name") or "").strip(), (user.get("last_name") or "").strip()] if part)
        if full_name:
            return full_name
        user_id = user.get("id")
        return f"user_{user_id}" if user_id is not None else "unknown"

    @staticmethod
    def _compact(text: str, *, max_len: int = 500) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= max_len:
            return cleaned
        return f"{cleaned[: max_len - 1]}…"

    def _build_user_prompt_with_context(
        self,
        *,
        user_text: str,
        reply_text: str | None,
        recent_messages: list[dict],
    ) -> str:
        context_lines: list[str] = []
        if reply_text:
            context_lines.append(f"Reply target: {self._compact(reply_text)}")
        for item in recent_messages:
            sender = item.get("sender_label") or "unknown"
            text = item.get("text") or ""
            if not text:
                continue
            context_lines.append(f"{sender}: {self._compact(text)}")

        if not context_lines:
            return user_text
        context_block = "\n".join(context_lines[-10:])
        return (
            "Контекст последних сообщений, доступных боту (используй для ответа, если релевантно):\n"
            f"{context_block}\n\n"
            "Текущий запрос пользователя:\n"
            f"{user_text}"
        )

    @staticmethod
    def _extract_reply_text(message: dict) -> str | None:
        reply_message = message.get("reply_to_message") or {}
        reply_text = (reply_message.get("text") or reply_message.get("caption") or "").strip()
        if reply_text:
            return reply_text

        external_reply = message.get("external_reply") or {}
        reply_text = (external_reply.get("text") or external_reply.get("caption") or "").strip()
        if reply_text:
            return reply_text

        origin = external_reply.get("origin") or {}
        sender_user = origin.get("sender_user") or {}
        sender_name = (
            sender_user.get("username")
            or " ".join(
                part
                for part in [sender_user.get("first_name", "").strip(), sender_user.get("last_name", "").strip()]
                if part
            )
            or origin.get("sender_user_name")
            or origin.get("author_signature")
        )
        origin_text = (origin.get("text") or "").strip()
        if origin_text:
            prefix = f"{sender_name}: " if sender_name else ""
            return f"{prefix}{origin_text}"
        return None

    @staticmethod
    def _scenario_filename(title: str) -> str:
        return "prompt.txt"

    async def _send_llm_answer(
        self,
        *,
        chat_id: int,
        answer: str,
    ) -> None:
        # Prefer Markdown for model-formatted answers, but gracefully fallback.
        try:
            await self.telegram.send_message(
                chat_id,
                answer,
                parse_mode="Markdown",
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Failed to send Markdown answer, fallback to plain text: %s", exc)
            await self.telegram.send_message(chat_id, answer)

    async def _answer_guest_query(self, *, guest_query_id: str, answer: str) -> None:
        try:
            await self.telegram.answer_guest_query(
                guest_query_id=guest_query_id,
                text=answer,
                parse_mode="Markdown",
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Failed to answer guest query with Markdown, fallback to plain text: %s", exc)
            await self.telegram.answer_guest_query(guest_query_id=guest_query_id, text=answer)

    async def _render_panel(self, chat_id: int, user_id: int) -> None:
        scenario_items = await self.storage.list_scenarios(user_id)
        state = await self.storage.get_chat_state(user_id)
        selected_scenario_id = state.get("selected_scenario_id")
        selected_scenario = None
        if selected_scenario_id is not None:
            selected_scenario = await self.storage.get_scenario(user_id, selected_scenario_id)
            if selected_scenario is None:
                await self.storage.update_chat_state(user_id, selected_scenario_id=None)

        if selected_scenario:
            text = self.panel.build_scenario_card_text(selected_scenario)
            markup = self.panel.build_scenario_card_markup(selected_scenario)
        else:
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

    async def _send_scenario_prompt_file(
        self,
        *,
        chat_id: int,
        scenario: dict,
    ) -> None:
        await self.telegram.send_text_document(
            chat_id=chat_id,
            filename=self._scenario_filename(scenario["title"]),
            text=scenario["system_prompt"],
            caption=f"Полный текст сценария: {scenario['title']}",
        )

    async def _handle_stateful_input(
        self,
        chat_id: int,
        user_id: int,
        text: str,
    ) -> bool:
        state = await self.storage.get_chat_state(user_id)
        if state["pending_action"] == "await_title":
            await self.storage.update_chat_state(
                user_id,
                pending_action="await_prompt",
                draft_title=text.strip(),
                delete_candidate_id=None,
                selected_scenario_id=None,
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
                await self.storage.update_chat_state(
                    user_id,
                    pending_action="await_title",
                    draft_title=None,
                    selected_scenario_id=None,
                )
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
                selected_scenario_id=None,
            )
            await self.telegram.send_message(chat_id, f"Сценарий «{draft_title}» добавлен.")
            await self._render_panel(chat_id, user_id)
            return True

        if state["pending_action"] == "await_prompt_edit":
            scenario_id = state.get("selected_scenario_id")
            if not scenario_id:
                await self.storage.update_chat_state(
                    user_id,
                    pending_action=None,
                    selected_scenario_id=None,
                )
                await self.telegram.send_message(chat_id, "Не удалось определить сценарий для редактирования. Откройте карточку еще раз.")
                return True

            try:
                updated = await self.scenarios.update_scenario_prompt(user_id, int(scenario_id), text.strip())
            except ValueError as exc:
                await self.telegram.send_message(chat_id, f"Не удалось обновить промпт: {exc}")
                return True

            await self.storage.update_chat_state(
                user_id,
                pending_action=None,
                draft_title=None,
                delete_candidate_id=None,
                selected_scenario_id=int(scenario_id) if updated else None,
            )
            if updated:
                await self.telegram.send_message(chat_id, "Промпт сценария обновлен.")
            else:
                await self.telegram.send_message(chat_id, "Сценарий не найден.")
            await self._render_panel(chat_id, user_id)
            return True
        return False

    async def handle_start(
        self,
        chat_id: int,
        telegram_user_id: int,
        *,
        show_panel: bool = False,
    ) -> None:
        user = await self.storage.get_or_create_user(telegram_user_id)
        await self.telegram.send_message(chat_id, "Бот активирован. Управляйте сценариями через панель ниже.")
        if show_panel:
            await self.storage.update_chat_state(user["id"], selected_scenario_id=None)
            await self._render_panel(chat_id, user["id"])

    async def handle_message(self, message: dict, *, source: str = "message") -> None:
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        chat_type = (chat.get("type") or "").lower()
        from_user = message.get("from", {})
        if from_user.get("is_bot"):
            self.logger.info(
                "Ignoring %s update from bot user: chat_id=%s chat_type=%s",
                source,
                chat_id,
                chat_type,
            )
            return
        telegram_user_id = from_user.get("id")
        if telegram_user_id is None or chat_id is None:
            return
        text = (message.get("text") or message.get("caption") or "").strip()
        if not text:
            self.logger.info(
                "Ignoring %s update without text/caption: chat_id=%s chat_type=%s",
                source,
                chat_id,
                chat_type,
            )
            return
        if chat_type != "private":
            self.logger.info("Ignoring regular message outside private chat: chat_id=%s chat_type=%s", chat_id, chat_type)
            return

        user = await self.storage.get_or_create_user(telegram_user_id)
        normalized_text = text.lower()

        if normalized_text in {"/start", "/start@" + self.bot_username}:
            await self.handle_start(chat_id, telegram_user_id, show_panel=True)
            return
        if normalized_text in {"/panel", "/panel@" + self.bot_username}:
            await self.storage.update_chat_state(user["id"], selected_scenario_id=None)
            await self._render_panel(chat_id, user["id"])
            return

        consumed = await self._handle_stateful_input(chat_id, user["id"], text)
        if consumed:
            return

        if normalized_text in {"cancel", "/cancel"}:
            await self.storage.update_chat_state(
                user["id"],
                pending_action=None,
                draft_title=None,
                delete_candidate_id=None,
                selected_scenario_id=None,
            )
            await self.telegram.send_message(chat_id, "Текущее действие отменено.")
            await self._render_panel(chat_id, user["id"])
            return

        await self._render_panel(chat_id, user["id"])

    async def handle_guest_message(self, message: dict) -> None:
        from_user = message.get("from", {})
        if from_user.get("is_bot"):
            self.logger.info(
                "Ignoring guest update from bot user: guest_query_id=%s",
                message.get("guest_query_id"),
            )
            return
        guest_query_id = message.get("guest_query_id")
        if not guest_query_id:
            self.logger.info("Ignoring guest message without guest_query_id")
            return

        chat = message.get("chat", {}) or {}
        guest_chat = message.get("guest_bot_caller_chat", {}) or {}
        chat_id = chat.get("id") or guest_chat.get("id")
        telegram_user_id = from_user.get("id")
        message_id = message.get("message_id")
        text = (message.get("text") or message.get("caption") or "").strip()
        if telegram_user_id is None or chat_id is None or not text:
            self.logger.info(
                "Ignoring guest message missing fields: chat_id=%s from_id=%s has_text=%s",
                chat_id,
                telegram_user_id,
                bool(text),
            )
            return

        cleaned_text = self._strip_mention(text) if self._is_mention_message(text) else text
        if not cleaned_text.strip():
            answer = "Сформулируйте запрос текстом или ответьте на предыдущее сообщение бота."
            await self._answer_guest_query(guest_query_id=guest_query_id, answer=answer)
            return

        enabled = await self.storage.get_any_enabled_scenario()
        if not enabled:
            answer = "Нет активного сценария. Включите сценарий в личном чате с ботом."
            self.logger.info("Skipping guest reply: no active scenario")
            await self._answer_guest_query(guest_query_id=guest_query_id, answer=answer)
            return

        reply_text = self._extract_reply_text(message)
        llm_user_text = self._build_user_prompt_with_context(
            user_text=cleaned_text,
            reply_text=reply_text,
            recent_messages=[],
        )
        self.logger.info(
            "Guest LLM context prepared: chat_id=%s reply_present=%s guest_query_id=%s",
            chat_id,
            bool(reply_text),
            guest_query_id,
        )
        try:
            result = await self.evolink.generate(system_prompt=enabled["system_prompt"], user_text=llm_user_text)
            answer = result["text"] or "Не удалось сгенерировать ответ."
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("LLM generation failed: %s", exc)
            answer = "Сервис модели временно недоступен. Попробуйте еще раз."
        await self._answer_guest_query(
            guest_query_id=guest_query_id,
            answer=answer,
        )

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
                selected_scenario_id=None,
            )
            await self.telegram.send_message(chat_id, "Введите название нового сценария.")
            return

        if data == "panel:refresh":
            await self.storage.update_chat_state(user_id, delete_candidate_id=None, selected_scenario_id=None)
            await self._render_panel(chat_id, user_id)
            return

        if data == "panel:back":
            await self.storage.update_chat_state(user_id, selected_scenario_id=None, delete_candidate_id=None)
            await self._render_panel(chat_id, user_id)
            return

        if data == "sc:deln":
            await self.storage.update_chat_state(user_id, delete_candidate_id=None, selected_scenario_id=None)
            await self._render_panel(chat_id, user_id)
            return

        if data.startswith("sc:view:"):
            try:
                scenario_id = int(data.split(":")[-1])
            except ValueError:
                await self.telegram.send_message(chat_id, "Некорректный идентификатор сценария.")
                return
            scenario = await self.storage.get_scenario(user_id, scenario_id)
            if not scenario:
                await self.telegram.send_message(chat_id, "Сценарий не найден.")
                await self.storage.update_chat_state(user_id, selected_scenario_id=None)
                await self._render_panel(chat_id, user_id)
                return
            await self.storage.update_chat_state(user_id, selected_scenario_id=scenario_id, delete_candidate_id=None)
            await self._render_panel(chat_id, user_id)
            await self._send_scenario_prompt_file(
                chat_id=chat_id,
                scenario=scenario,
            )
            return

        if data.startswith("sc:edit:"):
            try:
                scenario_id = int(data.split(":")[-1])
            except ValueError:
                await self.telegram.send_message(chat_id, "Некорректный идентификатор сценария.")
                return
            scenario = await self.storage.get_scenario(user_id, scenario_id)
            if not scenario:
                await self.telegram.send_message(chat_id, "Сценарий не найден.")
                await self.storage.update_chat_state(user_id, selected_scenario_id=None, pending_action=None)
                await self._render_panel(chat_id, user_id)
                return
            await self.storage.update_chat_state(
                user_id,
                pending_action="await_prompt_edit",
                selected_scenario_id=scenario_id,
                delete_candidate_id=None,
            )
            await self.telegram.send_message(
                chat_id,
                "Отправьте новый полный текст промпта для этого сценария следующим сообщением.",
            )
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
            await self.storage.update_chat_state(user_id, delete_candidate_id=None, selected_scenario_id=scenario_id)
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

        if data.startswith("sc:delete:") or data.startswith("sc:dely:"):
            try:
                scenario_id = int(data.split(":")[-1])
            except ValueError:
                await self.telegram.send_message(chat_id, "Некорректный идентификатор сценария.")
                return
            deleted = await self.scenarios.delete_scenario(user_id, scenario_id)
            await self.storage.update_chat_state(user_id, delete_candidate_id=None, selected_scenario_id=None)
            if deleted:
                await self.telegram.send_message(chat_id, "Сценарий удален.")
            else:
                await self.telegram.send_message(chat_id, "Сценарий уже удален или не найден.")
            await self._render_panel(chat_id, user_id)
