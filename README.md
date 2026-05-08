# Servant Bot

Telegram-бот в режиме Guest Bots (май 2026): используется через `@mention` в диалогах пользователей.

## Что реализовано

- Guest-only обработка: бот отвечает только по `@mention` или в reply на свое сообщение.
- Панель сценариев: добавить, включить/выключить, удалить с подтверждением.
- Ограничение на уровне БД: только один активный сценарий на пользователя.
- Диалог с LLM через Evolink (`primary` + `fallback` модель, retry/timeout).
- Webhook-режим Telegram.
- Docker-окружение и конфигурация через `.env`.

## Telegram API: практические ограничения (май 2026)

- Для инлайн-кнопок используется `callback_query`.
- Guest Mode: бот видит только сообщение с `@mention` и ответы в этой ветке.
- После нажатия кнопки обязательно вызывать `answerCallbackQuery`, иначе клиент показывает бесконечный прогресс.
- Поле `callback_data` ограничено 1-64 байтами: поэтому используются короткие префиксы (`sc:toggle:123`).
- Обновление панели выполняется через `editMessageText`, чтобы не спамить новыми сообщениями.
- Состояние пользователя (активный сценарий, шаг добавления сценария и т.д.) хранится в нашей БД.

## Переменные окружения

Скопируйте `.env.example` в `.env` и заполните значения:

- `TELEGRAM_BOT_TOKEN`
- `EVOLINK_API_KEY`
- `EVOLINK_MODEL_PRIMARY`
- `EVOLINK_MODEL_FALLBACK`
- `EVOLINK_STRICT_MODEL_VALIDATION`
- `WEBHOOK_PUBLIC_URL`
- `WEBHOOK_SECRET_TOKEN`
- `DB_PATH`

## Запуск в Docker

```bash
docker compose up --build
```

Сервис поднимется на `APP_PORT` (по умолчанию `8080`), healthcheck: `/healthz`.

На старте бот автоматически запрашивает свой username через `getMe`, вручную задавать его в `.env` не нужно.
Также выполняется проверка `EVOLINK_MODEL_PRIMARY/FALLBACK` через `GET /v1/models`. Если модель не найдена и `EVOLINK_STRICT_MODEL_VALIDATION=true`, сервис не запускается (fail-fast).
Базовые URL API захардкожены в `src/config.py` (`TELEGRAM_API_BASE`, `EVOLINK_BASE_URL`) и не задаются через `.env`.

## Nginx reverse proxy (HTTPS)

На сервере поднимаем только приложение:

```bash
docker compose up -d --build
```

Далее внешний `nginx` проксирует webhook в контейнер:

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.example;

    ssl_certificate /etc/letsencrypt/live/your-domain.example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.example/privkey.pem;

    location /telegram/webhook {
        proxy_pass http://127.0.0.1:8080/telegram/webhook;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /healthz {
        proxy_pass http://127.0.0.1:8080/healthz;
    }
}
```

Важно: `WEBHOOK_PUBLIC_URL` должен совпадать с публичным HTTPS-доменом, который обслуживает `nginx`.

## UX-флоу для пользователя

- `@bot_username панель` — показать панель сценариев.
- `➕ Добавить сценарий` — бот запросит название, потом роль/инструкцию.
- Нажатие на кнопку сценария (`🟢`/`🔴`) — переключает активность.
- `🗑` — запрос подтверждения удаления.
- `@bot_username ваш запрос` — ответ от активного сценария через Evolink.
- `@bot_username cancel` — отменить текущий step-by-step ввод.
