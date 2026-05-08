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

    async def _render_panel(self, chat_id: int, user_id: int, *, business_connection_id: str | None = None) -> None:
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
                    business_connection_id=business_connection_id,
                )
                return
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Failed to edit panel message, fallback to sendMessage: %s", exc)

        sent = await self.telegram.send_message(
            chat_id,
            text,
            reply_markup=markup,
            business_connection_id=business_connection_id,
        )
        await self.storage.update_chat_state(user_id, panel_message_id=sent["message_id"])

    async def _handle_stateful_input(
        self,
        chat_id: int,
        user_id: int,
        text: str,
        *,
        business_connection_id: str | None = None,
    ) -> bool:
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
                business_connection_id=business_connection_id,
            )
            return True

        if state["pending_action"] == "await_prompt":
            draft_title = (state.get("draft_title") or "").strip()
            if not draft_title:
                await self.storage.update_chat_state(user_id, pending_action="await_title", draft_title=None)
                await self.telegram.send_message(
                    chat_id,
                    "Нужен заголовок сценария. Отправьте название еще раз.",
                    business_connection_id=business_connection_id,
                )
                return True

            try:
                await self.scenarios.add_scenario(user_id, draft_title, text.strip())
            except ValueError as exc:
                await self.telegram.send_message(
                    chat_id,
                    f"Не удалось создать сценарий: {exc}",
                    business_connection_id=business_connection_id,
                )
                return True

            await self.storage.update_chat_state(
                user_id,
                pending_action=None,
                draft_title=None,
                delete_candidate_id=None,
            )
            await self.telegram.send_message(
                chat_id,
                f"Сценарий «{draft_title}» добавлен.",
                business_connection_id=business_connection_id,
            )
            await self._render_panel(chat_id, user_id, business_connection_id=business_connection_id)
            return True
        return False

    async def handle_start(
        self,
        chat_id: int,
        telegram_user_id: int,
        *,
        business_connection_id: str | None = None,
    ) -> None:
        await self.storage.get_or_create_user(telegram_user_id)
        await self.telegram.send_message(
            chat_id,
            "Бот активирован. Напишите сообщение — отвечу по активному сценарию.",
            business_connection_id=business_connection_id,
        )

    async def handle_message(self, message: dict, *, source: str = "message") -> None:
        chat = message.get("chat", {})
        chat_id = chat["id"]
        chat_type = (chat.get("type") or "").lower()
        is_private = chat_type == "private"
        business_connection_id = message.get("business_connection_id")
        from_user = message.get("from", {})
        telegram_user_id = from_user.get("id")
        if telegram_user_id is None:
            return
        message_id = message.get("message_id")
        text = (message.get("text") or message.get("caption") or "").strip()
        if not text:
            self.logger.info(
                "Ignoring %s update without text/caption: chat_id=%s chat_type=%s",
                source,
                chat_id,
                chat_type,
            )
            return
        sender_label = self._sender_label(from_user)
        await self.storage.append_chat_message(
            chat_id=chat_id,
            message_id=message_id if isinstance(message_id, int) else None,
            sender_label=sender_label,
            text=text,
            is_bot=bool(from_user.get("is_bot")),
        )

        user = await self.storage.get_or_create_user(telegram_user_id)
        normalized_text = text.lower()

        # Handle startup/panel commands before Guest-mode mention gating.
        if normalized_text in {"/start", "/start@" + self.bot_username}:
            await self.handle_start(
                chat_id,
                telegram_user_id,
                business_connection_id=business_connection_id,
            )
            return
        if normalized_text in {"/panel", "/panel@" + self.bot_username}:
            if is_private:
                await self.telegram.send_message(
                    chat_id,
                    "В личке панель отключена. Просто напишите сообщение — отвечу по активному сценарию.",
                    business_connection_id=business_connection_id,
                )
            else:
                await self._render_panel(chat_id, user["id"], business_connection_id=business_connection_id)
            return

        # Stateful scenario creation should work without mention/reply gating.
        consumed = await self._handle_stateful_input(
            chat_id,
            user["id"],
            text,
            business_connection_id=business_connection_id,
        )
        if consumed:
            return

        if normalized_text in {"cancel", "/cancel"}:
            await self.storage.update_chat_state(
                user["id"],
                pending_action=None,
                draft_title=None,
                delete_candidate_id=None,
            )
            await self.telegram.send_message(
                chat_id,
                "Текущее действие отменено.",
                business_connection_id=business_connection_id,
            )
            await self._render_panel(chat_id, user["id"], business_connection_id=business_connection_id)
            return

        # Guest-only mode: react only to explicit mention or reply to bot message.
        is_mention = self._is_mention_message(text)
        is_reply_to_bot = self._is_reply_to_bot(message)
        if not is_private and not is_mention and not is_reply_to_bot:
            self.logger.info(
                "Ignoring %s update without mention/reply: chat_id=%s chat_type=%s text=%r",
                source,
                chat_id,
                chat_type,
                text[:120],
            )
            return

        cleaned_text = text if is_private else (self._strip_mention(text) if is_mention else text)
        normalized = cleaned_text.strip().lower()
        if normalized in {"panel", "/panel"}:
            if is_private:
                await self.telegram.send_message(
                    chat_id,
                    "В личке панель отключена. Просто напишите сообщение — отвечу по активному сценарию.",
                    business_connection_id=business_connection_id,
                )
            else:
                await self._render_panel(chat_id, user["id"], business_connection_id=business_connection_id)
            return

        if not cleaned_text:
            await self.telegram.send_message(
                chat_id,
                "Опишите запрос рядом с упоминанием бота, например:\n"
                f"@{self.bot_username} панель\n"
                f"@{self.bot_username} критикуй мой текст",
                business_connection_id=business_connection_id,
            )
            return

        enabled = await self.storage.get_enabled_scenario(user["id"])
        if not enabled:
            await self.telegram.send_message(
                chat_id,
                "Нет активного сценария. Активируйте сценарий в управляющем чате и вернитесь сюда.",
                business_connection_id=business_connection_id,
            )
            return

        reply_text = None
        reply_message = message.get("reply_to_message") or {}
        if reply_message:
            reply_text = (reply_message.get("text") or reply_message.get("caption") or "").strip() or None
        recent_messages = await self.storage.get_recent_chat_messages(
            chat_id=chat_id,
            limit=10,
            exclude_message_id=message_id if isinstance(message_id, int) else None,
        )
        llm_user_text = self._build_user_prompt_with_context(
            user_text=cleaned_text,
            reply_text=reply_text,
            recent_messages=recent_messages,
        )
        self.logger.info(
            "LLM context prepared: chat_id=%s source=%s context_count=%s reply_present=%s",
            chat_id,
            source,
            len(recent_messages),
            bool(reply_text),
        )
        try:
            result = await self.evolink.generate(system_prompt=enabled["system_prompt"], user_text=llm_user_text)
            answer = result["text"] or "Не удалось сгенерировать ответ."
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("LLM generation failed: %s", exc)
            answer = "Сервис модели временно недоступен. Попробуйте еще раз."
        await self.telegram.send_message(chat_id, answer, business_connection_id=business_connection_id)

    async def handle_callback(self, callback_query: dict) -> None:
        callback_id = callback_query["id"]
        data = callback_query.get("data", "")
        message = callback_query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        business_connection_id = message.get("business_connection_id")
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
            await self.telegram.send_message(
                chat_id,
                "Введите название нового сценария.",
                business_connection_id=business_connection_id,
            )
            return

        if data == "panel:refresh":
            await self.storage.update_chat_state(user_id, delete_candidate_id=None)
            await self._render_panel(chat_id, user_id, business_connection_id=business_connection_id)
            return

        if data == "sc:deln":
            await self.storage.update_chat_state(user_id, delete_candidate_id=None)
            await self._render_panel(chat_id, user_id, business_connection_id=business_connection_id)
            return

        if data.startswith("sc:toggle:"):
            try:
                scenario_id = int(data.split(":")[-1])
            except ValueError:
                await self.telegram.send_message(
                    chat_id,
                    "Некорректный идентификатор сценария.",
                    business_connection_id=business_connection_id,
                )
                return
            changed = await self.scenarios.toggle_scenario(user_id, scenario_id)
            if not changed:
                await self.telegram.send_message(
                    chat_id,
                    "Сценарий не найден.",
                    business_connection_id=business_connection_id,
                )
            await self.storage.update_chat_state(user_id, delete_candidate_id=None)
            await self._render_panel(chat_id, user_id, business_connection_id=business_connection_id)
            return

        if data.startswith("sc:delask:"):
            try:
                scenario_id = int(data.split(":")[-1])
            except ValueError:
                await self.telegram.send_message(
                    chat_id,
                    "Некорректный идентификатор сценария.",
                    business_connection_id=business_connection_id,
                )
                return
            await self.storage.update_chat_state(user_id, delete_candidate_id=scenario_id)
            await self._render_panel(chat_id, user_id, business_connection_id=business_connection_id)
            return

        if data.startswith("sc:dely:"):
            try:
                scenario_id = int(data.split(":")[-1])
            except ValueError:
                await self.telegram.send_message(
                    chat_id,
                    "Некорректный идентификатор сценария.",
                    business_connection_id=business_connection_id,
                )
                return
            deleted = await self.scenarios.delete_scenario(user_id, scenario_id)
            await self.storage.update_chat_state(user_id, delete_candidate_id=None)
            if deleted:
                await self.telegram.send_message(
                    chat_id,
                    "Сценарий удален.",
                    business_connection_id=business_connection_id,
                )
            else:
                await self.telegram.send_message(
                    chat_id,
                    "Сценарий уже удален или не найден.",
                    business_connection_id=business_connection_id,
                )
            await self._render_panel(chat_id, user_id, business_connection_id=business_connection_id)
