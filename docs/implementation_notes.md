# Implementation Notes

## Компоненты

- `src/main.py` — FastAPI приложение, webhook endpoint, startup init.
- `src/bot_service.py` — оркестрация сообщений и callback-кнопок.
- `src/scenario_manager.py` — бизнес-правила сценариев и валидация.
- `src/storage.py` — SQLite доступ к данным.
- `src/db.py` — DDL и индексы.
- `src/evolink_client.py` — клиент к Evolink API с fallback/retry.
- `src/panel_renderer.py` — текст и inline-клавиатура панели.
- `src/telegram_client.py` — обертка над Bot API.

## Callback протокол

- `panel:add` — начать создание сценария.
- `panel:refresh` — принудительно обновить панель.
- `sc:toggle:{id}` — включить/выключить сценарий.
- `sc:delask:{id}` — запрос подтверждения удаления.
- `sc:dely:{id}` — подтвержденное удаление.
- `sc:deln` — отмена удаления.

Все callback-команды короче лимита 64 байта.

## Критерии приемки MVP

1. `@bot_username панель` показывает панель сценариев в guest-режиме.
2. Добавление сценария работает в два шага (title -> prompt).
3. При включении сценария автоматически отключается предыдущий активный.
4. Удаление требует подтверждения кнопкой.
5. При отсутствии активного сценария бот не идет в LLM и дает подсказку.
6. При активном сценарии и `@mention` бот отправляет ответ через Evolink.
7. Приложение запускается через `docker compose up --build`.
