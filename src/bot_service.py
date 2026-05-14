from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from src.panel_renderer import PanelRenderer
from src.scenario_manager import ScenarioManager
from src.storage import Storage
from src.telegram_client import TelegramClient


class BotService:
    TIME_RE = re.compile(r"^(?P<hour>\d{1,3}):(?P<minute>\d{2})$")
    DATE_RE = re.compile(r"^(0[1-9]|[12]\d|3[01])\.(0[1-9]|1[0-2])$")
    MOSCOW_TZ = timezone(timedelta(hours=3))

    def __init__(
        self,
        *,
        storage: Storage,
        scenarios: ScenarioManager,
        panel: PanelRenderer,
        telegram: TelegramClient,
        bot_username: str | None,
    ) -> None:
        self.storage = storage
        self.scenarios = scenarios
        self.panel = panel
        self.telegram = telegram
        self.bot_username = bot_username.lstrip("@").lower() if bot_username else ""
        self.logger = logging.getLogger(__name__)

    def set_bot_username(self, bot_username: str) -> None:
        self.bot_username = bot_username.lstrip("@").lower()

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _to_iso(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _from_iso(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value)

    @staticmethod
    def _message_datetime(message: dict) -> datetime:
        unix_ts = message.get("date")
        if unix_ts is None:
            return BotService._utc_now()
        return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc)

    @staticmethod
    def _reply_text(message: dict) -> str:
        return (message.get("text") or message.get("caption") or "").strip()

    @staticmethod
    def _parse_wait_time(raw: str) -> int:
        match = BotService.TIME_RE.match(raw.strip())
        if not match:
            raise ValueError("Введите время в формате чч:мм.")
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        if hour > 100 or minute > 59:
            raise ValueError("Время указано некорректно.")
        return hour * 60 + minute

    @staticmethod
    def _parse_clock_time(raw: str) -> str:
        minutes = BotService._parse_wait_time(raw)
        hour = minutes // 60
        minute = minutes % 60
        if hour > 23:
            raise ValueError("Для рабочего времени используйте часы от 00 до 23.")
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def _parse_holidays(raw: str) -> list[str]:
        items = [line.strip() for line in raw.splitlines() if line.strip()]
        for item in items:
            if not BotService.DATE_RE.match(item):
                raise ValueError("Дополнительные выходные вводятся в формате ДД.ММ, по одной дате в строке.")
        return items

    @staticmethod
    def _new_draft() -> dict:
        return {
            "title": "",
            "reply_text": "",
            "steel_pause_minutes": 5,
            "not_answer_twice": True,
            "hot_pause_minutes": None,
            "use_weekend_rules": False,
            "weekend_days": [6, 7],
            "extra_holidays": [],
            "active_day_mode": "always",
            "use_work_hours": False,
            "work_start": None,
            "work_end": None,
            "template_code": "custom",
        }

    @staticmethod
    def _scenario_to_draft(scenario: dict) -> dict:
        return {
            "title": scenario["title"],
            "reply_text": scenario["reply_text"],
            "steel_pause_minutes": scenario["steel_pause_minutes"],
            "not_answer_twice": scenario["not_answer_twice"],
            "hot_pause_minutes": scenario.get("hot_pause_minutes"),
            "use_weekend_rules": scenario["use_weekend_rules"],
            "weekend_days": scenario.get("weekend_days") or [6, 7],
            "extra_holidays": scenario.get("extra_holidays") or [],
            "active_day_mode": scenario.get("active_day_mode") or "always",
            "use_work_hours": scenario["use_work_hours"],
            "work_start": scenario.get("work_start"),
            "work_end": scenario.get("work_end"),
            "template_code": scenario.get("template_code") or "custom",
        }

    def _enrich_draft_labels(self, draft: dict) -> dict:
        result = dict(draft)
        hot_pause = result.get("hot_pause_minutes")
        result["hot_pause_label"] = "выключена" if hot_pause is None else f"{hot_pause // 60:02d}:{hot_pause % 60:02d}"
        if result.get("use_weekend_rules"):
            mode_map = {
                "always": "Всегда отвечать",
                "weekdays": "Только в будни",
                "weekends": "Только в выходные",
            }
            result["day_mode_label"] = mode_map.get(result.get("active_day_mode"), "Всегда отвечать")
        else:
            result["day_mode_label"] = "без разделения на дни"
        if result.get("use_work_hours") and result.get("work_start") and result.get("work_end"):
            result["work_hours_label"] = f"{result['work_start']} - {result['work_end']}"
        else:
            result["work_hours_label"] = "без ограничения"
        return result

    async def _render_panel(self, chat_id: int, user_id: int) -> None:
        state = await self.storage.get_chat_state(user_id)
        current_view = state.get("current_view") or "main"
        selected_scenario_id = state.get("selected_scenario_id")
        selected_scenario = await self.storage.get_scenario(user_id, selected_scenario_id) if selected_scenario_id else None
        user = await self.storage.get_user_by_id(user_id)

        if current_view == "help":
            text = self.panel.build_help_text()
            markup = self.panel.build_help_markup()
        elif current_view == "auto_list":
            items = await self.storage.list_scenarios(user_id)
            text = self.panel.build_autoresponders_text(items)
            markup = self.panel.build_autoresponders_markup(items)
        elif current_view == "scenario_card" and selected_scenario and user:
            text = self.panel.build_scenario_card_text(selected_scenario, int(user["telegram_user_id"]))
            markup = self.panel.build_scenario_card_markup(selected_scenario)
        elif current_view == "scenario_delete" and selected_scenario:
            text, markup = self.panel.build_delete_confirmation(selected_scenario["id"], selected_scenario["title"])
        elif current_view == "weekend_menu" and selected_scenario:
            text = self.panel.build_weekend_menu_text(selected_scenario)
            markup = self.panel.build_weekend_menu_markup(selected_scenario)
        elif current_view == "work_menu" and selected_scenario:
            text = self.panel.build_work_menu_text(selected_scenario)
            markup = self.panel.build_work_menu_markup(selected_scenario)
        elif current_view == "wizard":
            draft = self._enrich_draft_labels(state.get("draft_data") or {})
            step = state.get("pending_field") or "title"
            text = self.panel.build_wizard_text(step, draft, editing=bool(draft.get("_editing_scenario_id")))
            markup = self.panel.build_wizard_markup(step, draft, editing=bool(draft.get("_editing_scenario_id")))
        else:
            text = self.panel.build_main_menu_text()
            markup = self.panel.build_main_menu_markup()

        panel_message_id = state.get("panel_message_id")
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
                self.logger.warning("Failed to edit panel message, sending a new one: %s", exc)

        sent = await self.telegram.send_message(chat_id, text, reply_markup=markup)
        await self.storage.update_chat_state(user_id, panel_message_id=sent["message_id"])

    async def _show_view(self, chat_id: int, user_id: int, view: str, **state_updates: object) -> None:
        await self.storage.update_chat_state(user_id, current_view=view, **state_updates)
        await self._render_panel(chat_id, user_id)

    async def _start_new_wizard(self, chat_id: int, user_id: int) -> None:
        draft = self._new_draft()
        draft["_mode"] = "new"
        draft["_editing_scenario_id"] = None
        await self._show_view(
            chat_id,
            user_id,
            "wizard",
            pending_field="title",
            draft_data=draft,
            step_stack=[],
            selected_scenario_id=None,
        )

    async def _start_edit_wizard(self, chat_id: int, user_id: int, scenario: dict, step: str, mode: str, back_target: str) -> None:
        draft = self._scenario_to_draft(scenario)
        draft["_mode"] = mode
        draft["_editing_scenario_id"] = scenario["id"]
        await self._show_view(
            chat_id,
            user_id,
            "wizard",
            pending_field=step,
            draft_data=draft,
            step_stack=[back_target],
            selected_scenario_id=scenario["id"],
        )

    async def _wizard_next(self, chat_id: int, user_id: int, next_step: str) -> None:
        state = await self.storage.get_chat_state(user_id)
        stack = list(state.get("step_stack") or [])
        current_step = state.get("pending_field")
        if current_step:
            stack.append(current_step)
        await self.storage.update_chat_state(user_id, pending_field=next_step, step_stack=stack)
        await self._render_panel(chat_id, user_id)

    async def _wizard_back(self, chat_id: int, user_id: int) -> None:
        state = await self.storage.get_chat_state(user_id)
        stack = list(state.get("step_stack") or [])
        if not stack:
            await self._show_view(chat_id, user_id, "auto_list", pending_field=None, draft_data={}, step_stack=[])
            return
        previous = stack.pop()
        if previous == "return:card":
            await self._show_view(chat_id, user_id, "scenario_card", pending_field=None, draft_data={}, step_stack=[])
            return
        if previous == "return:weekend_menu":
            await self._show_view(chat_id, user_id, "weekend_menu", pending_field=None, draft_data={}, step_stack=[])
            return
        if previous == "return:work_menu":
            await self._show_view(chat_id, user_id, "work_menu", pending_field=None, draft_data={}, step_stack=[])
            return
        await self.storage.update_chat_state(user_id, pending_field=previous, step_stack=stack)
        await self._render_panel(chat_id, user_id)

    async def _save_draft(self, user_id: int, draft: dict) -> int:
        scenario_id = draft.get("_editing_scenario_id")
        payload = {key: value for key, value in draft.items() if not key.startswith("_")}
        if scenario_id:
            updated = await self.scenarios.update_scenario(user_id, int(scenario_id), payload)
            if not updated:
                raise ValueError("Сценарий не найден.")
            return int(scenario_id)
        return await self.scenarios.add_scenario(user_id, payload)

    async def _handle_wizard_text_input(self, chat_id: int, user_id: int, text: str) -> bool:
        state = await self.storage.get_chat_state(user_id)
        if state.get("current_view") != "wizard":
            return False
        step = state.get("pending_field")
        draft = dict(state.get("draft_data") or {})
        mode = draft.get("_mode") or "new"
        if not step:
            return False
        try:
            if step == "title":
                draft["title"] = text.strip()
                await self.storage.update_chat_state(user_id, draft_data=draft)
                if mode == "edit_title":
                    await self._save_draft(user_id, draft)
                    await self._show_view(chat_id, user_id, "scenario_card", pending_field=None, draft_data={}, step_stack=[])
                    return True
                await self._wizard_next(chat_id, user_id, "reply_text")
                return True
            if step == "reply_text":
                draft["reply_text"] = text.strip()
                await self.storage.update_chat_state(user_id, draft_data=draft)
                if mode == "edit_text":
                    await self._save_draft(user_id, draft)
                    await self._show_view(chat_id, user_id, "scenario_card", pending_field=None, draft_data={}, step_stack=[])
                    return True
                await self._wizard_next(chat_id, user_id, "template")
                return True
            if step == "steel_pause":
                draft["steel_pause_minutes"] = int(text.strip())
                await self.storage.update_chat_state(user_id, draft_data=draft)
                if mode == "edit_steel":
                    await self._save_draft(user_id, draft)
                    await self._show_view(chat_id, user_id, "scenario_card", pending_field=None, draft_data={}, step_stack=[])
                    return True
                if draft.get("template_code") in {"away", "soon"}:
                    await self._wizard_next(chat_id, user_id, "weekend_rules")
                else:
                    await self._wizard_next(chat_id, user_id, "repeat")
                return True
            if step == "hot_pause":
                draft["hot_pause_minutes"] = self._parse_wait_time(text)
                await self.storage.update_chat_state(user_id, draft_data=draft)
                if mode == "edit_repeat":
                    await self._save_draft(user_id, draft)
                    await self._show_view(chat_id, user_id, "scenario_card", pending_field=None, draft_data={}, step_stack=[])
                    return True
                await self._wizard_next(chat_id, user_id, "weekend_rules")
                return True
            if step == "holiday_dates":
                draft["extra_holidays"] = self._parse_holidays(text)
                await self.storage.update_chat_state(user_id, draft_data=draft)
                if mode == "edit_holidays":
                    await self._save_draft(user_id, draft)
                    await self._show_view(chat_id, user_id, "weekend_menu", pending_field=None, draft_data={}, step_stack=[])
                    return True
                await self._wizard_next(chat_id, user_id, "active_day_mode")
                return True
            if step == "work_start":
                draft["work_start"] = self._parse_clock_time(text)
                await self.storage.update_chat_state(user_id, draft_data=draft)
                if mode == "edit_work_start":
                    await self._save_draft(user_id, draft)
                    await self._show_view(chat_id, user_id, "work_menu", pending_field=None, draft_data={}, step_stack=[])
                    return True
                await self._wizard_next(chat_id, user_id, "work_end")
                return True
            if step == "work_end":
                draft["work_end"] = self._parse_clock_time(text)
                await self.storage.update_chat_state(user_id, draft_data=draft)
                if mode == "edit_work_end":
                    await self._save_draft(user_id, draft)
                    await self._show_view(chat_id, user_id, "work_menu", pending_field=None, draft_data={}, step_stack=[])
                    return True
                await self._wizard_next(chat_id, user_id, "confirm")
                return True
        except ValueError as exc:
            await self.telegram.send_message(chat_id, str(exc))
            return True
        return False

    async def handle_start(self, chat_id: int, telegram_user_id: int) -> None:
        user = await self.storage.get_or_create_user(telegram_user_id)
        await self._show_view(
            chat_id,
            user["id"],
            "main",
            pending_field=None,
            draft_data={},
            step_stack=[],
            selected_scenario_id=None,
        )

    async def handle_message(self, message: dict, *, source: str = "message") -> None:
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        chat_type = (chat.get("type") or "").lower()
        from_user = message.get("from", {})
        if from_user.get("is_bot"):
            return
        telegram_user_id = from_user.get("id")
        if telegram_user_id is None or chat_id is None:
            return
        if chat_type == "private":
            text = self._reply_text(message)
            user = await self.storage.get_or_create_user(telegram_user_id)
            normalized = text.lower()
            if normalized in {"", "/start", "/start@" + self.bot_username}:
                await self.handle_start(chat_id, telegram_user_id)
                return
            if normalized in {"/cancel", "cancel"}:
                await self._show_view(
                    chat_id,
                    user["id"],
                    "auto_list",
                    pending_field=None,
                    draft_data={},
                    step_stack=[],
                    selected_scenario_id=None,
                )
                return
            consumed = await self._handle_wizard_text_input(chat_id, user["id"], text)
            if consumed:
                return
            await self._render_panel(chat_id, user["id"])
            return
        return

    async def handle_business_connection(self, connection: dict) -> None:
        business_connection_id = connection.get("id")
        owner = (connection.get("user") or {}).get("id")
        if not business_connection_id or owner is None:
            return
        user = await self.storage.get_or_create_user(int(owner))
        rights = connection.get("rights") or {}
        await self.storage.upsert_business_connection(
            business_connection_id=business_connection_id,
            owner_user_id=user["id"],
            owner_telegram_id=int(owner),
            owner_private_chat_id=connection.get("user_chat_id"),
            can_reply=bool(rights.get("can_reply")),
            can_read_messages=bool(rights.get("can_read_messages")),
            raw_rights=rights,
        )

    async def _resolve_business_connection(self, business_connection_id: str) -> dict | None:
        cached = await self.storage.get_business_connection(business_connection_id)
        if cached:
            scenario = await self.storage.get_enabled_scenario(cached["owner_user_id"])
            if scenario:
                cached["scenario"] = scenario
                return cached
            self.logger.info(
                "Business connection %s resolved from cache, but owner_user_id=%s has no enabled scenario.",
                business_connection_id,
                cached["owner_user_id"],
            )
        try:
            connection = await self.telegram.get_business_connection(business_connection_id)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Failed to load business connection %s: %s", business_connection_id, exc)
            return None
        owner_telegram_id = (connection.get("user") or {}).get("id")
        if owner_telegram_id is None:
            self.logger.info("Business connection %s has no owner user in Telegram response.", business_connection_id)
            return None
        user = await self.storage.get_or_create_user(int(owner_telegram_id))
        rights = connection.get("rights") or {}
        await self.storage.upsert_business_connection(
            business_connection_id=business_connection_id,
            owner_user_id=user["id"],
            owner_telegram_id=int(owner_telegram_id),
            owner_private_chat_id=connection.get("user_chat_id"),
            can_reply=bool(rights.get("can_reply")),
            can_read_messages=bool(rights.get("can_read_messages")),
            raw_rights=rights,
        )
        scenario = await self.storage.get_enabled_scenario(user["id"])
        if not scenario:
            self.logger.info(
                "Business connection %s resolved from Telegram, but owner telegram_id=%s user_id=%s has no enabled scenario.",
                business_connection_id,
                owner_telegram_id,
                user["id"],
            )
            return None
        return {
            "business_connection_id": business_connection_id,
            "owner_user_id": user["id"],
            "owner_telegram_id": int(owner_telegram_id),
            "owner_private_chat_id": connection.get("user_chat_id"),
            "can_reply": bool(rights.get("can_reply")),
            "can_read_messages": bool(rights.get("can_read_messages")),
            "raw_rights": rights,
            "scenario": scenario,
        }

    async def handle_business_message(self, message: dict, *, source: str = "business_message") -> None:
        from_user = message.get("from", {})
        if from_user.get("is_bot") or message.get("sender_business_bot"):
            self.logger.info("Ignoring business message from bot sender. source=%s", source)
            return
        business_connection_id = message.get("business_connection_id")
        chat_id = (message.get("chat") or {}).get("id")
        sender_telegram_id = from_user.get("id")
        if not business_connection_id or chat_id is None or sender_telegram_id is None:
            self.logger.info(
                "Ignoring business message with missing fields: source=%s connection=%s chat_id=%s sender_id=%s",
                source,
                business_connection_id,
                chat_id,
                sender_telegram_id,
            )
            return
        owner = await self._resolve_business_connection(business_connection_id)
        if not owner:
            self.logger.info(
                "Skipping business message: no resolved owner/scenario for connection=%s chat_id=%s source=%s",
                business_connection_id,
                chat_id,
                source,
            )
            return
        scenario = owner["scenario"]
        if not (scenario.get("reply_text") or "").strip():
            self.logger.info(
                "Business message skipped because scenario_id=%s has empty reply_text. connection=%s chat_id=%s",
                scenario["id"],
                business_connection_id,
                chat_id,
            )
            return
        message_dt = self._message_datetime(message)
        message_iso = self._to_iso(message_dt)
        if int(sender_telegram_id) == int(owner["owner_telegram_id"]):
            await self.storage.mark_owner_activity(
                chat_id=chat_id,
                owner_user_id=owner["owner_user_id"],
                owner_message_at=message_iso,
            )
            self.logger.info(
                "Business message treated as owner activity; timer cleared. connection=%s chat_id=%s owner=%s",
                business_connection_id,
                chat_id,
                owner["owner_telegram_id"],
            )
            return
        if not owner.get("can_reply"):
            self.logger.info("Business connection %s has no can_reply right.", business_connection_id)
            return
        if not self._scenario_allows_time(scenario, message_dt):
            self.logger.info(
                "Business message blocked by schedule rules. connection=%s chat_id=%s scenario_id=%s",
                business_connection_id,
                chat_id,
                scenario["id"],
            )
            return
        conversation = await self.storage.get_conversation_state(chat_id, owner["owner_user_id"])
        last_bot_reply_at = self._from_iso(conversation.get("last_bot_reply_at")) if conversation else None
        last_owner_message_at = self._from_iso(conversation.get("last_owner_message_at")) if conversation else None
        owner_replied_after_bot = bool(last_bot_reply_at and last_owner_message_at and last_owner_message_at > last_bot_reply_at)
        if last_bot_reply_at and not owner_replied_after_bot and scenario["not_answer_twice"]:
            self.logger.info(
                "Business message skipped because repeated replies are disabled. connection=%s chat_id=%s scenario_id=%s",
                business_connection_id,
                chat_id,
                scenario["id"],
            )
            return
        due_dt = message_dt + timedelta(minutes=int(scenario["steel_pause_minutes"]))
        if last_bot_reply_at and not owner_replied_after_bot and scenario.get("hot_pause_minutes") is not None:
            hot_pause_deadline = last_bot_reply_at + timedelta(minutes=int(scenario["hot_pause_minutes"]))
            if hot_pause_deadline > due_dt:
                due_dt = hot_pause_deadline
        await self.storage.schedule_conversation_reply(
            chat_id=chat_id,
            owner_user_id=owner["owner_user_id"],
            scenario_id=scenario["id"],
            business_connection_id=business_connection_id,
            due_at=self._to_iso(due_dt),
            message_id=message.get("message_id"),
            customer_message_at=message_iso,
        )
        self.logger.info(
            "Scheduled business auto-reply for chat_id=%s owner=%s connection=%s due_at=%s source=%s",
            chat_id,
            owner["owner_telegram_id"],
            business_connection_id,
            self._to_iso(due_dt),
            source,
        )

    def _scenario_allows_time(self, scenario: dict, now_dt: datetime) -> bool:
        local_dt = now_dt.astimezone(self.MOSCOW_TZ)
        if scenario.get("use_weekend_rules"):
            weekend_days = {int(day) for day in scenario.get("weekend_days") or []}
            extra_holidays = set(scenario.get("extra_holidays") or [])
            is_weekend = local_dt.isoweekday() in weekend_days or local_dt.strftime("%d.%m") in extra_holidays
            mode = scenario.get("active_day_mode") or "always"
            if mode == "weekdays" and is_weekend:
                return False
            if mode == "weekends" and not is_weekend:
                return False
        if scenario.get("use_work_hours"):
            start_raw = scenario.get("work_start")
            end_raw = scenario.get("work_end")
            if start_raw and end_raw:
                start_minutes = self._parse_wait_time(start_raw)
                end_minutes = self._parse_wait_time(end_raw)
                current_minutes = local_dt.hour * 60 + local_dt.minute
                if start_minutes != end_minutes:
                    if start_minutes < end_minutes and not (start_minutes <= current_minutes < end_minutes):
                        return False
                    if start_minutes > end_minutes and not (current_minutes >= start_minutes or current_minutes < end_minutes):
                        return False
        return True

    async def _handle_managed_chat_message(self, message: dict, *, source: str) -> None:
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        if chat_id is None:
            return
        owner = await self._resolve_managed_chat(chat_id, chat.get("title"))
        if not owner:
            return
        scenario = owner["scenario"]
        from_user = message.get("from", {})
        sender_telegram_id = from_user.get("id")
        if sender_telegram_id is None:
            return
        message_dt = self._message_datetime(message)
        message_iso = self._to_iso(message_dt)
        if sender_telegram_id == owner["owner_telegram_id"]:
            await self.storage.mark_owner_activity(
                chat_id=chat_id,
                owner_user_id=owner["owner_user_id"],
                owner_message_at=message_iso,
            )
            return
        if not self._scenario_allows_time(scenario, message_dt):
            return
        conversation = await self.storage.get_conversation_state(chat_id, owner["owner_user_id"])
        last_bot_reply_at = self._from_iso(conversation.get("last_bot_reply_at")) if conversation else None
        last_owner_message_at = self._from_iso(conversation.get("last_owner_message_at")) if conversation else None
        owner_replied_after_bot = bool(last_bot_reply_at and last_owner_message_at and last_owner_message_at > last_bot_reply_at)
        if last_bot_reply_at and not owner_replied_after_bot and scenario["not_answer_twice"]:
            return
        due_dt = message_dt + timedelta(minutes=int(scenario["steel_pause_minutes"]))
        if last_bot_reply_at and not owner_replied_after_bot and scenario.get("hot_pause_minutes") is not None:
            hot_pause_deadline = last_bot_reply_at + timedelta(minutes=int(scenario["hot_pause_minutes"]))
            if hot_pause_deadline > due_dt:
                due_dt = hot_pause_deadline
        await self.storage.schedule_conversation_reply(
            chat_id=chat_id,
            owner_user_id=owner["owner_user_id"],
            scenario_id=scenario["id"],
            due_at=self._to_iso(due_dt),
            message_id=message.get("message_id"),
            customer_message_at=message_iso,
        )
        self.logger.info(
            "Scheduled auto-reply for chat_id=%s owner=%s due_at=%s source=%s",
            chat_id,
            owner["owner_telegram_id"],
            self._to_iso(due_dt),
            source,
        )

    async def run_scheduler_loop(self, poll_seconds: int) -> None:
        while True:
            now = self._utc_now()
            try:
                due_items = await self.storage.list_due_conversations(self._to_iso(now))
                for item in due_items:
                    last_customer = self._from_iso(item.get("last_customer_message_at"))
                    last_owner = self._from_iso(item.get("last_owner_message_at"))
                    if last_customer and last_owner and last_owner >= last_customer:
                        await self.storage.clear_waiting_reply(chat_id=item["chat_id"], owner_user_id=item["owner_user_id"])
                        continue
                    if not self._scenario_allows_time(item, now):
                        await self.storage.clear_waiting_reply(chat_id=item["chat_id"], owner_user_id=item["owner_user_id"])
                        continue
                    if not (item.get("reply_text") or "").strip():
                        self.logger.info(
                            "Dropping scheduled auto-reply because scenario_id=%s has empty reply_text. chat_id=%s connection=%s",
                            item["scenario_id"],
                            item["chat_id"],
                            item.get("business_connection_id"),
                        )
                        await self.storage.clear_waiting_reply(chat_id=item["chat_id"], owner_user_id=item["owner_user_id"])
                        continue
                    sent = await self.telegram.send_message(
                        item["chat_id"],
                        item["reply_text"],
                        business_connection_id=item.get("business_connection_id"),
                    )
                    await self.storage.mark_bot_replied(
                        chat_id=item["chat_id"],
                        owner_user_id=item["owner_user_id"],
                        replied_at=self._to_iso(now),
                        message_id=sent.get("message_id"),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("Scheduler iteration failed: %s", exc)
            await asyncio.sleep(max(3, poll_seconds))

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
        await self.telegram.answer_callback_query(callback_id)

        if data == "menu:main":
            await self._show_view(chat_id, user_id, "main", selected_scenario_id=None)
            return
        if data == "menu:auto":
            await self._show_view(chat_id, user_id, "auto_list", selected_scenario_id=None)
            return
        if data == "menu:help":
            await self._show_view(chat_id, user_id, "help")
            return
        if data == "auto:add":
            await self._start_new_wizard(chat_id, user_id)
            return
        if data == "wiz:back":
            await self._wizard_back(chat_id, user_id)
            return

        if data.startswith("sc:view:"):
            scenario_id = int(data.rsplit(":", 1)[-1])
            if not await self.storage.get_scenario(user_id, scenario_id):
                await self.telegram.send_message(chat_id, "Сценарий не найден.")
                return
            await self._show_view(chat_id, user_id, "scenario_card", selected_scenario_id=scenario_id)
            return
        if data.startswith("sc:toggle:"):
            scenario_id = int(data.rsplit(":", 1)[-1])
            if not await self.scenarios.toggle_scenario(user_id, scenario_id):
                await self.telegram.send_message(chat_id, "Сценарий не найден.")
                return
            await self._show_view(chat_id, user_id, "scenario_card", selected_scenario_id=scenario_id)
            return
        if data.startswith("sc:delask:"):
            scenario_id = int(data.rsplit(":", 1)[-1])
            await self._show_view(chat_id, user_id, "scenario_delete", selected_scenario_id=scenario_id)
            return
        if data.startswith("sc:delete:"):
            scenario_id = int(data.rsplit(":", 1)[-1])
            if not await self.scenarios.delete_scenario(user_id, scenario_id):
                await self.telegram.send_message(chat_id, "Сценарий не найден.")
                return
            await self._show_view(chat_id, user_id, "auto_list", selected_scenario_id=None)
            return
        if data.startswith("sc:edit:"):
            _, _, field, scenario_id_raw = data.split(":")
            scenario_id = int(scenario_id_raw)
            scenario = await self.storage.get_scenario(user_id, scenario_id)
            if not scenario:
                await self.telegram.send_message(chat_id, "Сценарий не найден.")
                return
            if field == "title":
                await self._start_edit_wizard(chat_id, user_id, scenario, "title", "edit_title", "return:card")
                return
            if field == "text":
                await self._start_edit_wizard(chat_id, user_id, scenario, "reply_text", "edit_text", "return:card")
                return
            if field == "steel":
                await self._start_edit_wizard(chat_id, user_id, scenario, "steel_pause", "edit_steel", "return:card")
                return
            if field == "repeat":
                await self._start_edit_wizard(chat_id, user_id, scenario, "repeat", "edit_repeat", "return:card")
                return
            if field == "weekend":
                await self._show_view(chat_id, user_id, "weekend_menu", selected_scenario_id=scenario_id)
                return
            if field == "work":
                await self._show_view(chat_id, user_id, "work_menu", selected_scenario_id=scenario_id)
                return

        if data.startswith("we:toggle:"):
            scenario_id = int(data.rsplit(":", 1)[-1])
            scenario = await self.storage.get_scenario(user_id, scenario_id)
            if not scenario:
                return
            payload = self._scenario_to_draft(scenario)
            payload["use_weekend_rules"] = not scenario["use_weekend_rules"]
            await self.scenarios.update_scenario(user_id, scenario_id, payload)
            await self._show_view(chat_id, user_id, "weekend_menu", selected_scenario_id=scenario_id)
            return
        if data.startswith("we:day:"):
            _, _, day_raw, scenario_id_raw = data.split(":")
            scenario_id = int(scenario_id_raw)
            scenario = await self.storage.get_scenario(user_id, scenario_id)
            if not scenario:
                return
            payload = self._scenario_to_draft(scenario)
            selected = set(payload.get("weekend_days") or [])
            day = int(day_raw)
            if day in selected:
                selected.remove(day)
            else:
                selected.add(day)
            payload["use_weekend_rules"] = True
            payload["weekend_days"] = sorted(selected)
            await self.scenarios.update_scenario(user_id, scenario_id, payload)
            await self._show_view(chat_id, user_id, "weekend_menu", selected_scenario_id=scenario_id)
            return
        if data.startswith("we:mode:"):
            _, _, mode, scenario_id_raw = data.split(":")
            scenario_id = int(scenario_id_raw)
            scenario = await self.storage.get_scenario(user_id, scenario_id)
            if not scenario:
                return
            payload = self._scenario_to_draft(scenario)
            payload["use_weekend_rules"] = True
            payload["active_day_mode"] = mode
            await self.scenarios.update_scenario(user_id, scenario_id, payload)
            await self._show_view(chat_id, user_id, "weekend_menu", selected_scenario_id=scenario_id)
            return
        if data.startswith("we:hol:"):
            scenario_id = int(data.rsplit(":", 1)[-1])
            scenario = await self.storage.get_scenario(user_id, scenario_id)
            if not scenario:
                return
            await self._start_edit_wizard(chat_id, user_id, scenario, "holiday_dates", "edit_holidays", "return:weekend_menu")
            return

        if data.startswith("wh:toggle:"):
            scenario_id = int(data.rsplit(":", 1)[-1])
            scenario = await self.storage.get_scenario(user_id, scenario_id)
            if not scenario:
                return
            payload = self._scenario_to_draft(scenario)
            payload["use_work_hours"] = not scenario["use_work_hours"]
            if not payload["use_work_hours"]:
                payload["work_start"] = None
                payload["work_end"] = None
            elif not payload.get("work_start"):
                payload["work_start"] = "09:00"
                payload["work_end"] = "18:00"
            await self.scenarios.update_scenario(user_id, scenario_id, payload)
            await self._show_view(chat_id, user_id, "work_menu", selected_scenario_id=scenario_id)
            return
        if data.startswith("wh:start:"):
            scenario_id = int(data.rsplit(":", 1)[-1])
            scenario = await self.storage.get_scenario(user_id, scenario_id)
            if not scenario:
                return
            await self._start_edit_wizard(chat_id, user_id, scenario, "work_start", "edit_work_start", "return:work_menu")
            return
        if data.startswith("wh:end:"):
            scenario_id = int(data.rsplit(":", 1)[-1])
            scenario = await self.storage.get_scenario(user_id, scenario_id)
            if not scenario:
                return
            await self._start_edit_wizard(chat_id, user_id, scenario, "work_end", "edit_work_end", "return:work_menu")
            return

        state = await self.storage.get_chat_state(user_id)
        draft = dict(state.get("draft_data") or {})
        mode = draft.get("_mode") or "new"

        if data.startswith("wiz:template:"):
            template = data.rsplit(":", 1)[-1]
            draft["template_code"] = template
            if template == "away":
                draft["not_answer_twice"] = False
                draft["hot_pause_minutes"] = 10
            elif template == "soon":
                draft["not_answer_twice"] = False
                draft["hot_pause_minutes"] = None
            else:
                draft["not_answer_twice"] = True
                draft["hot_pause_minutes"] = None
            await self.storage.update_chat_state(user_id, draft_data=draft)
            await self._wizard_next(chat_id, user_id, "steel_pause")
            return
        if data == "wiz:repeat:yes":
            draft["not_answer_twice"] = False
            await self.storage.update_chat_state(user_id, draft_data=draft)
            await self._wizard_next(chat_id, user_id, "hot_pause")
            return
        if data == "wiz:repeat:no":
            draft["not_answer_twice"] = True
            draft["hot_pause_minutes"] = None
            await self.storage.update_chat_state(user_id, draft_data=draft)
            if mode == "edit_repeat":
                await self._save_draft(user_id, draft)
                await self._show_view(chat_id, user_id, "scenario_card", pending_field=None, draft_data={}, step_stack=[])
                return
            await self._wizard_next(chat_id, user_id, "weekend_rules")
            return
        if data == "wiz:weekend:yes":
            draft["use_weekend_rules"] = True
            await self.storage.update_chat_state(user_id, draft_data=draft)
            await self._wizard_next(chat_id, user_id, "weekend_days")
            return
        if data == "wiz:weekend:no":
            draft["use_weekend_rules"] = False
            draft["active_day_mode"] = "always"
            await self.storage.update_chat_state(user_id, draft_data=draft)
            await self._wizard_next(chat_id, user_id, "work_hours")
            return
        if data.startswith("wiz:wday:"):
            day = int(data.rsplit(":", 1)[-1])
            selected = set(draft.get("weekend_days") or [])
            if day in selected:
                selected.remove(day)
            else:
                selected.add(day)
            draft["weekend_days"] = sorted(selected)
            await self.storage.update_chat_state(user_id, draft_data=draft)
            await self._render_panel(chat_id, user_id)
            return
        if data == "wiz:next:holiday_dates":
            await self._wizard_next(chat_id, user_id, "holiday_dates")
            return
        if data == "wiz:hol:skip":
            draft["extra_holidays"] = []
            await self.storage.update_chat_state(user_id, draft_data=draft)
            if mode == "edit_holidays":
                await self._save_draft(user_id, draft)
                await self._show_view(chat_id, user_id, "weekend_menu", pending_field=None, draft_data={}, step_stack=[])
                return
            await self._wizard_next(chat_id, user_id, "active_day_mode")
            return
        if data == "wiz:next:active_day_mode":
            await self._wizard_next(chat_id, user_id, "active_day_mode")
            return
        if data.startswith("wiz:daymode:"):
            draft["active_day_mode"] = data.rsplit(":", 1)[-1]
            await self.storage.update_chat_state(user_id, draft_data=draft)
            await self._wizard_next(chat_id, user_id, "work_hours")
            return
        if data == "wiz:work:yes":
            draft["use_work_hours"] = True
            await self.storage.update_chat_state(user_id, draft_data=draft)
            await self._wizard_next(chat_id, user_id, "work_start")
            return
        if data == "wiz:work:no":
            draft["use_work_hours"] = False
            draft["work_start"] = None
            draft["work_end"] = None
            await self.storage.update_chat_state(user_id, draft_data=draft)
            await self._wizard_next(chat_id, user_id, "confirm")
            return
        if data.startswith("wiz:save:"):
            try:
                scenario_id = await self._save_draft(user_id, draft)
            except ValueError as exc:
                await self.telegram.send_message(chat_id, f"Не удалось сохранить сценарий: {exc}")
                return
            await self._show_view(
                chat_id,
                user_id,
                "scenario_card",
                selected_scenario_id=scenario_id,
                pending_field=None,
                draft_data={},
                step_stack=[],
            )
