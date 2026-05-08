from __future__ import annotations


class PanelRenderer:
    @staticmethod
    def build_panel_text(scenarios: list[dict]) -> str:
        if not scenarios:
            return (
                "Панель сценариев.\n\n"
                "Сценариев пока нет.\n"
                "Нажмите «Добавить сценарий», чтобы создать первый режим ответа."
            )
        lines: list[str] = ["Панель сценариев.\n"]
        for scenario in scenarios:
            marker = "🟢" if scenario["is_enabled"] else "🔴"
            lines.append(f"{marker} {scenario['title']}")
        lines.append("\nОдновременно может быть включен только один сценарий.")
        return "\n".join(lines)

    @staticmethod
    def _scenario_row(scenario: dict) -> list[dict]:
        marker = "🟢" if scenario["is_enabled"] else "🔴"
        return [{"text": f"{marker} {scenario['title']}", "callback_data": f"sc:view:{scenario['id']}"}]

    @staticmethod
    def build_scenario_card_text(scenario: dict) -> str:
        marker = "🟢" if scenario["is_enabled"] else "🔴"
        prompt = (scenario.get("system_prompt") or "").strip()
        preview = " ".join(prompt.split())
        if len(preview) > 220:
            preview = f"{preview[:219]}…"
        return (
            "Карточка сценария.\n\n"
            f"{marker} {scenario['title']}\n\n"
            f"Превью:\n{preview or 'Промпт пуст.'}\n\n"
            "Полный текст приложен отдельным `.txt` файлом."
        )

    @staticmethod
    def build_scenario_card_markup(scenario: dict) -> dict:
        toggle_text = "Выключить" if scenario["is_enabled"] else "Включить"
        rows = [
            [{"text": toggle_text, "callback_data": f"sc:toggle:{scenario['id']}"}],
            [{"text": "Удалить", "callback_data": f"sc:delete:{scenario['id']}"}],
            [{"text": "⬅ Назад к списку", "callback_data": "panel:back"}],
        ]
        return {"inline_keyboard": rows}

    def build_panel_markup(self, scenarios: list[dict], delete_candidate_id: int | None) -> dict:
        rows: list[list[dict]] = []
        for scenario in scenarios:
            rows.append(self._scenario_row(scenario))
        rows.append([{"text": "➕ Добавить сценарий", "callback_data": "panel:add"}])
        rows.append([{"text": "🔄 Обновить", "callback_data": "panel:refresh"}])
        return {"inline_keyboard": rows}
