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
        return [
            {
                "text": f"{marker} {scenario['title']}",
                "callback_data": f"sc:toggle:{scenario['id']}",
            },
            {
                "text": "🗑",
                "callback_data": f"sc:delask:{scenario['id']}",
            },
        ]

    def build_panel_markup(self, scenarios: list[dict], delete_candidate_id: int | None) -> dict:
        rows: list[list[dict]] = []
        for scenario in scenarios:
            rows.append(self._scenario_row(scenario))
            if delete_candidate_id and scenario["id"] == delete_candidate_id:
                rows.append(
                    [
                        {"text": "Подтвердить удаление", "callback_data": f"sc:dely:{scenario['id']}"},
                        {"text": "Отмена", "callback_data": "sc:deln"},
                    ]
                )
        rows.append([{"text": "➕ Добавить сценарий", "callback_data": "panel:add"}])
        rows.append([{"text": "🔄 Обновить", "callback_data": "panel:refresh"}])
        return {"inline_keyboard": rows}
