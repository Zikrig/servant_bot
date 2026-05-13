from __future__ import annotations


class PanelRenderer:
    DAY_LABELS = {
        1: "Пн",
        2: "Вт",
        3: "Ср",
        4: "Чт",
        5: "Пт",
        6: "Сб",
        7: "Вс",
    }
    DAY_LABELS_LONG = {
        1: "Понедельник",
        2: "Вторник",
        3: "Среда",
        4: "Четверг",
        5: "Пятница",
        6: "Суббота",
        7: "Воскресенье",
    }

    @staticmethod
    def _indicator(enabled: bool) -> str:
        return "🟢" if enabled else "🔴"

    def _day_label_list(self, days: list[int]) -> str:
        if not days:
            return "не выбраны"
        return ", ".join(self.DAY_LABELS.get(day, str(day)) for day in sorted(days))

    @staticmethod
    def _bool_label(value: bool, yes: str = "Да", no: str = "Нет") -> str:
        return yes if value else no

    def format_repeat_summary(self, scenario: dict) -> str:
        if scenario["not_answer_twice"]:
            return "только один раз за переписку"
        hot_pause = scenario.get("hot_pause_minutes")
        if hot_pause is None:
            return "разрешено, без дополнительной горячей паузы"
        hours = hot_pause // 60
        minutes = hot_pause % 60
        return f"разрешено, повторно не раньше чем через {hours:02d}:{minutes:02d}"

    def format_day_summary(self, scenario: dict) -> str:
        if not scenario["use_weekend_rules"]:
            return "без разделения на будни и выходные"
        mode_map = {
            "always": "Всегда отвечать",
            "weekdays": "Отвечать только в будни",
            "weekends": "Отвечать только в выходные",
        }
        holidays = scenario.get("extra_holidays") or []
        extra = "\nДоп. выходные: " + ", ".join(holidays) if holidays else "\nДоп. выходные: не указаны"
        return (
            f"{mode_map.get(scenario['active_day_mode'], 'Всегда отвечать')}\n"
            f"Выходные дни недели: {self._day_label_list(scenario.get('weekend_days') or [])}"
            f"{extra}"
        )

    @staticmethod
    def format_work_summary(scenario: dict) -> str:
        if not scenario["use_work_hours"]:
            return "без ограничения по времени"
        return f"дежурство с {scenario['work_start']} до {scenario['work_end']}"

    def build_main_menu_text(self) -> str:
        return (
            "Привет.\n\n"
            "Здесь можно настроить автоответчики для чатов, где вы управляете перепиской и добавили бота администратором.\n"
            "Сначала создайте сценарий, затем включите его. После этого бот будет ждать вашу паузу и отвечать только по заданным условиям."
        )

    @staticmethod
    def build_main_menu_markup() -> dict:
        return {
            "inline_keyboard": [
                [{"text": "Автоответчики", "callback_data": "menu:auto"}],
                [{"text": "Как это работает", "callback_data": "menu:help"}],
            ]
        }

    def build_help_text(self) -> str:
        return (
            "Как это работает\n\n"
            "Сценарий нужен, чтобы бот подстраховал вас в чате, если клиент пишет, а вы молчите дольше заданной паузы.\n\n"
            "Что умеет сценарий:\n"
            "1. Ждать заданное число минут после последнего сообщения клиента.\n"
            "2. Сбрасывать таймер, если клиент написал еще раз до ответа.\n"
            "3. Полностью отменять автоответ, если вы сами успели ответить.\n"
            "4. Ограничивать повторные ответы в одной переписке.\n"
            "5. Работать только в будни, выходные или всегда.\n"
            "6. Работать только в указанные часы дежурства.\n\n"
            "Что важно:\n"
            "- бот должен быть администратором в нужном чате;\n"
            "- владелец сценария должен быть зарегистрирован у бота;\n"
            "- одновременно у вас может быть включен только один сценарий, чтобы не было конфликта правил;\n"
            "- текст ответа сохраняется с переносами строк, но без вложений."
        )

    @staticmethod
    def build_help_markup() -> dict:
        return {"inline_keyboard": [[{"text": "Назад", "callback_data": "menu:main"}]]}

    def build_autoresponders_text(self, scenarios: list[dict]) -> str:
        if not scenarios:
            return (
                "Автоответчики\n\n"
                "У вас пока нет сценариев. Создайте первый и включите его, чтобы бот начал отвечать в управляемых чатах."
            )
        return (
            "Автоответчики\n\n"
            "Нажмите на сценарий, чтобы открыть карточку и поменять параметры.\n"
            "Зеленый индикатор показывает включенный сценарий."
        )

    def build_autoresponders_markup(self, scenarios: list[dict]) -> dict:
        rows: list[list[dict]] = []
        for scenario in scenarios:
            rows.append(
                [
                    {
                        "text": f"{self._indicator(scenario['is_enabled'])} {scenario['title']}",
                        "callback_data": f"sc:view:{scenario['id']}",
                    }
                ]
            )
        rows.append([{"text": "➕ Добавить", "callback_data": "auto:add"}])
        rows.append([{"text": "Назад", "callback_data": "menu:main"}])
        return {"inline_keyboard": rows}

    def build_scenario_card_text(self, scenario: dict, owner_telegram_id: int) -> str:
        return (
            f"{self._indicator(scenario['is_enabled'])} {scenario['title']}\n\n"
            f"Текст ответа:\n{scenario['reply_text']}\n\n"
            f"Владелец: {owner_telegram_id}\n"
            f"Пауза перед ответом: {scenario['steel_pause_minutes']} мин.\n"
            f"Повторные ответы: {self.format_repeat_summary(scenario)}\n"
            f"Выходные и дни: {self.format_day_summary(scenario)}\n"
            f"Рабочее время: {self.format_work_summary(scenario)}"
        )

    def build_scenario_card_markup(self, scenario: dict) -> dict:
        enabled_label = "🟢 Включен" if scenario["is_enabled"] else "🔴 Выключен"
        return {
            "inline_keyboard": [
                [{"text": enabled_label, "callback_data": f"sc:toggle:{scenario['id']}"}],
                [{"text": "Название", "callback_data": f"sc:edit:title:{scenario['id']}"}],
                [{"text": "Текст ответа", "callback_data": f"sc:edit:text:{scenario['id']}"}],
                [{"text": "Пауза перед ответом", "callback_data": f"sc:edit:steel:{scenario['id']}"}],
                [{"text": "Повторные ответы", "callback_data": f"sc:edit:repeat:{scenario['id']}"}],
                [{"text": "Выходные и дни", "callback_data": f"sc:edit:weekend:{scenario['id']}"}],
                [{"text": "Рабочее время", "callback_data": f"sc:edit:work:{scenario['id']}"}],
                [{"text": "Удалить", "callback_data": f"sc:delask:{scenario['id']}"}],
                [{"text": "Назад", "callback_data": "menu:auto"}],
            ]
        }

    def build_delete_confirmation(self, scenario_id: int, title: str) -> tuple[str, dict]:
        text = f"Удалить автоответчик «{title}»?"
        markup = {
            "inline_keyboard": [
                [{"text": "Да, удалить", "callback_data": f"sc:delete:{scenario_id}"}],
                [{"text": "Нет, назад", "callback_data": f"sc:view:{scenario_id}"}],
            ]
        }
        return text, markup

    def build_weekend_menu_text(self, scenario: dict) -> str:
        mode_map = {
            "always": "Всегда отвечать",
            "weekdays": "Отвечать только в будни",
            "weekends": "Отвечать только в выходные",
        }
        holidays = scenario.get("extra_holidays") or []
        return (
            "Выходные и дни\n\n"
            "Здесь вы говорите боту, какие дни считать выходными и когда этот сценарий вообще должен применяться.\n\n"
            f"Индикатор правил: {self._indicator(scenario['use_weekend_rules'])}\n"
            f"Дни недели: {self._day_label_list(scenario.get('weekend_days') or [])}\n"
            f"Дополнительные выходные: {', '.join(holidays) if holidays else 'не указаны'}\n"
            f"Режим ответа: {mode_map.get(scenario['active_day_mode'], 'Всегда отвечать')}"
        )

    def build_weekend_menu_markup(self, scenario: dict) -> dict:
        rows = [
            [
                {
                    "text": f"{self._indicator(scenario['use_weekend_rules'])} Учитывать выходные",
                    "callback_data": f"we:toggle:{scenario['id']}",
                }
            ]
        ]
        day_row: list[dict] = []
        selected = set(scenario.get("weekend_days") or [])
        for day in range(1, 8):
            marker = "🟢" if day in selected else "🔴"
            day_row.append({"text": f"{marker} {self.DAY_LABELS[day]}", "callback_data": f"we:day:{day}:{scenario['id']}"})
        rows.append(day_row)
        rows.append([{"text": "Доп. выходные даты", "callback_data": f"we:hol:{scenario['id']}"}])
        mode = scenario.get("active_day_mode") or "always"
        rows.append(
            [
                {"text": ("🟢 " if mode == "weekends" else "⚪ ") + "Выходные", "callback_data": f"we:mode:weekends:{scenario['id']}"},
                {"text": ("🟢 " if mode == "weekdays" else "⚪ ") + "Будни", "callback_data": f"we:mode:weekdays:{scenario['id']}"},
            ]
        )
        rows.append([{"text": ("🟢 " if mode == "always" else "⚪ ") + "Всегда отвечать", "callback_data": f"we:mode:always:{scenario['id']}"}])
        rows.append([{"text": "Назад", "callback_data": f"sc:view:{scenario['id']}"}])
        return {"inline_keyboard": rows}

    def build_work_menu_text(self, scenario: dict) -> str:
        return (
            "Рабочее время\n\n"
            "Этот параметр ограничивает часы, в которые бот вообще может сработать.\n\n"
            f"Индикатор ограничения: {self._indicator(scenario['use_work_hours'])}\n"
            f"Начало дежурства: {scenario.get('work_start') or 'не задано'}\n"
            f"Конец дежурства: {scenario.get('work_end') or 'не задано'}"
        )

    def build_work_menu_markup(self, scenario: dict) -> dict:
        return {
            "inline_keyboard": [
                [{"text": f"{self._indicator(scenario['use_work_hours'])} Ограничить по времени", "callback_data": f"wh:toggle:{scenario['id']}"}],
                [{"text": "Начальное время", "callback_data": f"wh:start:{scenario['id']}"}],
                [{"text": "Конечное время", "callback_data": f"wh:end:{scenario['id']}"}],
                [{"text": "Назад", "callback_data": f"sc:view:{scenario['id']}"}],
            ]
        }

    def build_wizard_text(self, step: str, draft: dict, *, editing: bool = False) -> str:
        title = "Редактирование автоответчика" if editing else "Новый автоответчик"
        if step == "title":
            return f"{title}\n\nШаг 1. Введите название сценария."
        if step == "reply_text":
            return (
                f"{title}\n\nШаг 2. Отправьте текст, которым бот должен отвечать.\n"
                "Сохранятся переносы строк, но вложения не сохраняются."
            )
        if step == "template":
            return (
                f"{title}\n\nШаг 3. Выберите заготовку.\n\n"
                "Сценарий «Меня нет»\n"
                "«Прошу беспокоить только в рабочее время - по вторникам с 4:00 до 4:15»\n\n"
                "Сценарий «Буду через минуту»\n"
                "«Да, конечно вы нам нужны дорогой клиент, я мою руки, умоляю не ищите другие варианты, яужетут»\n\n"
                "Свой сценарий\n"
                "Полная настройка всех параметров вручную."
            )
        if step == "steel_pause":
            return (
                f"{title}\n\n"
                "Через сколько минут бот должен ответить, если владелец молчит?\n"
                "Если клиент пишет повторно до ответа, таймер начнется заново."
            )
        if step == "repeat":
            return f"{title}\n\nМожно ли боту отвечать повторно в одной переписке?"
        if step == "hot_pause":
            return (
                f"{title}\n\n"
                "Через сколько времени можно отвечать повторно?\n"
                "Введите время в формате чч:мм. Можно указывать до 100 часов."
            )
        if step == "weekend_rules":
            return f"{title}\n\nНужно ли сценарию учитывать будни и выходные?"
        if step == "weekend_days":
            return (
                f"{title}\n\n"
                "Выберите дни недели, которые считаются выходными.\n"
                "Кнопки можно переключать сколько угодно. Когда закончите, нажмите «Дальше»."
            )
        if step == "holiday_dates":
            holidays = draft.get("extra_holidays") or []
            current = "\n".join(holidays) if holidays else "Пока ничего не указано."
            return (
                f"{title}\n\n"
                "Отправьте дополнительные даты выходных в формате ДД.ММ, по одной в строке.\n"
                "Это можно будет изменить позже.\n\n"
                f"Сейчас:\n{current}"
            )
        if step == "active_day_mode":
            return f"{title}\n\nКогда этот сценарий должен отвечать?"
        if step == "work_hours":
            return f"{title}\n\nНужно ли ограничить сценарий по времени дежурства?"
        if step == "work_start":
            return f"{title}\n\nВведите начальное время дежурства в формате чч:мм."
        if step == "work_end":
            return f"{title}\n\nВведите конечное время дежурства в формате чч:мм."
        if step == "confirm":
            return (
                f"{title}\n\n"
                f"Название: {draft.get('title') or 'не указано'}\n"
                f"Текст ответа:\n{draft.get('reply_text') or 'не указано'}\n\n"
                f"Пауза перед ответом: {draft.get('steel_pause_minutes', 'не указано')} мин.\n"
                f"Повторные ответы: {'нет' if draft.get('not_answer_twice', True) else 'да'}\n"
                f"Горячая пауза: {draft.get('hot_pause_label') or 'выключена'}\n"
                f"Выходные и дни: {draft.get('day_mode_label') or 'не настроены'}\n"
                f"Рабочее время: {draft.get('work_hours_label') or 'без ограничения'}\n\n"
                "Все готово?"
            )
        return title

    def build_wizard_markup(self, step: str, draft: dict, *, editing: bool = False) -> dict:
        rows: list[list[dict]] = []
        if step == "template":
            rows.extend(
                [
                    [{"text": "Сценарий «Меня нет»", "callback_data": "wiz:template:away"}],
                    [{"text": "Сценарий «Буду через минуту»", "callback_data": "wiz:template:soon"}],
                    [{"text": "Свой сценарий", "callback_data": "wiz:template:custom"}],
                ]
            )
        elif step == "repeat":
            rows.extend(
                [
                    [{"text": "Да", "callback_data": "wiz:repeat:yes"}],
                    [{"text": "Нет", "callback_data": "wiz:repeat:no"}],
                ]
            )
        elif step == "weekend_rules":
            rows.extend(
                [
                    [{"text": "Да", "callback_data": "wiz:weekend:yes"}],
                    [{"text": "Нет", "callback_data": "wiz:weekend:no"}],
                ]
            )
        elif step == "weekend_days":
            selected = set(draft.get("weekend_days") or [])
            row: list[dict] = []
            for day in range(1, 8):
                marker = "🟢" if day in selected else "🔴"
                row.append({"text": f"{marker} {self.DAY_LABELS[day]}", "callback_data": f"wiz:wday:{day}"})
            rows.append(row)
            rows.append([{"text": "Дальше", "callback_data": "wiz:next:holiday_dates"}])
        elif step == "holiday_dates":
            rows.extend(
                [
                    [{"text": "Не сейчас", "callback_data": "wiz:hol:skip"}],
                    [{"text": "Дальше", "callback_data": "wiz:next:active_day_mode"}],
                ]
            )
        elif step == "active_day_mode":
            rows.extend(
                [
                    [{"text": "Отвечать только в выходные", "callback_data": "wiz:daymode:weekends"}],
                    [{"text": "Отвечать только в будни", "callback_data": "wiz:daymode:weekdays"}],
                    [{"text": "Всегда отвечать", "callback_data": "wiz:daymode:always"}],
                ]
            )
        elif step == "work_hours":
            rows.extend(
                [
                    [{"text": "Да", "callback_data": "wiz:work:yes"}],
                    [{"text": "Нет", "callback_data": "wiz:work:no"}],
                ]
            )
        elif step == "confirm":
            save_cb = "wiz:save:edit" if editing else "wiz:save:new"
            rows.extend(
                [
                    [{"text": "Сохранить", "callback_data": save_cb}],
                    [{"text": "Назад", "callback_data": "wiz:back"}],
                ]
            )
            return {"inline_keyboard": rows}

        rows.append([{"text": "Назад", "callback_data": "wiz:back"}])
        return {"inline_keyboard": rows}
