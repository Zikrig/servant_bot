# Servant Bot

Telegram-бот для автоответчиков в чатах, где владелец сценария управляет перепиской и добавил бота администратором.

## Что реализовано

- Личное меню с приветствием, разделом автоответчиков и экраном `Как это работает`.
- Пошаговый мастер создания сценария: название, текст ответа, шаблон, паузы, выходные и рабочее время.
- Карточка сценария с отдельными подменю для выходных и рабочего времени.
- Ограничение на уровне БД: одновременно включен только один сценарий на пользователя.
- Отложенные автоответы по таймеру: если владелец не ответил сам, бот отправляет заготовленный текст в управляемый чат.
- Webhook-режим Telegram.
- Docker-окружение и конфигурация через `.env`.

## Telegram API: практические ограничения (май 2026)

- Для инлайн-кнопок используется `callback_query`.
- После нажатия кнопки обязательно вызывать `answerCallbackQuery`, иначе клиент показывает бесконечный прогресс.
- Поле `callback_data` ограничено 1-64 байтами: поэтому используются короткие префиксы (`sc:view:123`, `we:day:6:123`).
- Обновление панели выполняется через `editMessageText`, чтобы не спамить новыми сообщениями.
- Состояние пользователя и незавершенный мастер сценария хранятся в SQLite.
- Для автоответов бот должен быть администратором в целевом чате.

## Переменные окружения

Скопируйте `.env.example` в `.env` и заполните значения:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_BOT_USERNAME` (необязательно, на старте бот все равно уточняет username через `getMe`)
- `WEBHOOK_PUBLIC_URL`
- `WEBHOOK_SECRET_TOKEN`
- `DB_PATH`
- `SCHEDULER_POLL_SECONDS`

## Запуск в Docker

```bash
docker compose up --build
```

Сервис поднимется на `APP_PORT` (по умолчанию `8080`), healthcheck: `/healthz`.

На старте бот автоматически запрашивает свой username через `getMe`, вручную задавать его в `.env` необязательно.
Отложенные ответы отправляются фоновым циклом внутри приложения. Частота проверки задается через `SCHEDULER_POLL_SECONDS`.
Базовый URL Telegram API захардкожен в `src/config.py` и не задается через `.env`.

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

- `/start` в личном чате — показать приветствие и главное меню.
- `Автоответчики` — открыть список сценариев.
- `➕ Добавить` — запустить мастер создания сценария.
- Нажатие на сценарий — открыть карточку и редактирование параметров.
- Включенный сценарий применяется в чатах, где его владелец является зарегистрированным админом, а бот имеет права администратора.
