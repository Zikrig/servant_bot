from __future__ import annotations

from dataclasses import dataclass

from src.storage import Storage


@dataclass
class ValidationLimits:
    max_scenarios_per_user: int
    max_title_len: int
    max_prompt_len: int


class ScenarioManager:
    def __init__(self, storage: Storage, limits: ValidationLimits) -> None:
        self.storage = storage
        self.limits = limits

    async def add_scenario(self, user_id: int, title: str, system_prompt: str) -> int:
        title = title.strip()
        system_prompt = system_prompt.strip()
        if not title:
            raise ValueError("Название сценария не может быть пустым.")
        if len(title) > self.limits.max_title_len:
            raise ValueError(f"Название слишком длинное (макс. {self.limits.max_title_len}).")
        if not system_prompt:
            raise ValueError("Промпт сценария не может быть пустым.")
        if len(system_prompt) > self.limits.max_prompt_len:
            raise ValueError(f"Промпт слишком длинный (макс. {self.limits.max_prompt_len}).")

        count = await self.storage.count_scenarios(user_id)
        if count >= self.limits.max_scenarios_per_user:
            raise ValueError(f"Достигнут лимит сценариев ({self.limits.max_scenarios_per_user}).")

        return await self.storage.create_scenario(user_id, title, system_prompt)

    async def delete_scenario(self, user_id: int, scenario_id: int) -> bool:
        return await self.storage.delete_scenario(user_id, scenario_id)

    async def toggle_scenario(self, user_id: int, scenario_id: int) -> bool:
        scenario = await self.storage.get_scenario(user_id, scenario_id)
        if not scenario:
            return False
        if scenario["is_enabled"]:
            return await self.storage.disable_scenario(user_id, scenario_id)
        return await self.storage.set_enabled_scenario(user_id, scenario_id)
