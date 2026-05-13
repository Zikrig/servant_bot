from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.storage import Storage


@dataclass
class ValidationLimits:
    max_scenarios_per_user: int
    max_title_len: int
    max_reply_len: int
    max_wait_hours: int = 100


class ScenarioManager:
    def __init__(self, storage: Storage, limits: ValidationLimits) -> None:
        self.storage = storage
        self.limits = limits

    def validate_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = (payload.get("title") or "").strip()
        reply_text = (payload.get("reply_text") or "").strip()
        if not title:
            raise ValueError("Название сценария не может быть пустым.")
        if len(title) > self.limits.max_title_len:
            raise ValueError(f"Название слишком длинное (макс. {self.limits.max_title_len}).")
        if not reply_text:
            raise ValueError("Текст автоответа не может быть пустым.")
        if len(reply_text) > self.limits.max_reply_len:
            raise ValueError(f"Текст автоответа слишком длинный (макс. {self.limits.max_reply_len}).")

        steel_pause_minutes = int(payload.get("steel_pause_minutes") or 0)
        max_minutes = self.limits.max_wait_hours * 60
        if steel_pause_minutes <= 0 or steel_pause_minutes > max_minutes:
            raise ValueError(f"Пауза ожидания должна быть от 1 до {max_minutes} минут.")

        not_answer_twice = bool(payload.get("not_answer_twice"))
        hot_pause_minutes = payload.get("hot_pause_minutes")
        if not_answer_twice:
            hot_pause_minutes = None
        elif hot_pause_minutes is not None:
            hot_pause_minutes = int(hot_pause_minutes)
            if hot_pause_minutes < 0 or hot_pause_minutes > max_minutes:
                raise ValueError(f"Пауза перед повторным ответом должна быть от 0 до {max_minutes} минут.")

        use_weekend_rules = bool(payload.get("use_weekend_rules"))
        weekend_days = sorted({int(day) for day in payload.get("weekend_days", []) if 1 <= int(day) <= 7})
        extra_holidays = [item for item in payload.get("extra_holidays", []) if item]
        active_day_mode = payload.get("active_day_mode") or "always"
        if active_day_mode not in {"always", "weekdays", "weekends"}:
            raise ValueError("Некорректный режим дней.")
        if not use_weekend_rules:
            weekend_days = []
            extra_holidays = []
            active_day_mode = "always"

        use_work_hours = bool(payload.get("use_work_hours"))
        work_start = payload.get("work_start")
        work_end = payload.get("work_end")
        if use_work_hours and (not work_start or not work_end):
            raise ValueError("Для ограничения по времени нужны начало и конец дежурства.")
        if not use_work_hours:
            work_start = None
            work_end = None

        return {
            "title": title,
            "reply_text": reply_text,
            "steel_pause_minutes": steel_pause_minutes,
            "not_answer_twice": not_answer_twice,
            "hot_pause_minutes": hot_pause_minutes,
            "use_weekend_rules": use_weekend_rules,
            "weekend_days": weekend_days,
            "extra_holidays": extra_holidays,
            "active_day_mode": active_day_mode,
            "use_work_hours": use_work_hours,
            "work_start": work_start,
            "work_end": work_end,
            "template_code": payload.get("template_code") or "custom",
        }

    async def add_scenario(self, user_id: int, payload: dict[str, Any]) -> int:
        count = await self.storage.count_scenarios(user_id)
        if count >= self.limits.max_scenarios_per_user:
            raise ValueError(f"Достигнут лимит сценариев ({self.limits.max_scenarios_per_user}).")
        return await self.storage.create_scenario(user_id, self.validate_payload(payload))

    async def delete_scenario(self, user_id: int, scenario_id: int) -> bool:
        return await self.storage.delete_scenario(user_id, scenario_id)

    async def update_scenario(self, user_id: int, scenario_id: int, payload: dict[str, Any]) -> bool:
        return await self.storage.update_scenario(user_id, scenario_id, self.validate_payload(payload))

    async def toggle_scenario(self, user_id: int, scenario_id: int) -> bool:
        scenario = await self.storage.get_scenario(user_id, scenario_id)
        if not scenario:
            return False
        if scenario["is_enabled"]:
            return await self.storage.disable_scenario(user_id, scenario_id)
        return await self.storage.set_enabled_scenario(user_id, scenario_id)
