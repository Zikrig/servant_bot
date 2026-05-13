# Telegram API Notes (May 2026)

Этот файл фиксирует технические решения и реальные наблюдения по Bot API 10.0 для текущей реализации.

## Какие апдейты бывают

### `message`

Обычное сообщение в чате с ботом.

- Приходит в личке и в обычных чатах, где бот является участником.
- Используется для панели управления сценариями.
- На такие сообщения бот отвечает обычными методами вроде `sendMessage`.

### `guest_message`

Сообщение в Guest Mode, когда бота тегают в чате, где он не является участником, или продолжают reply-ветку, начатую guest-ботом.

- Приходит только если у бота в `getMe` выставлено `supports_guest_queries=true`. Причем указывать это можно только в botfather АППЕ
- Для ответа используется не `sendMessage`, а `answerGuestQuery`.
- В `Message` появляются guest-поля:
  - `guest_query_id`
  - `guest_bot_caller_user`
  - `guest_bot_caller_chat`
- Если `supports_guest_queries=false`, Telegram вообще не присылает `guest_message`, даже если код подписан на этот тип апдейта.

### `business_message`

Сообщения которые приходят когда бот менеджерит чат.

- Приходит только если бот действительно подключен к бизнес-аккаунту.
- Для ответа обычно нужен `business_connection_id`.
- Это отдельный поток апдейтов, не связанный с Guest Mode.
- В текущей версии проекта business-ветка отключена и не используется в runtime.

## Используемые методы в текущем проекте

- `setWebhook` — прием апдейтов в webhook-режиме.
- `sendMessage` — отправка сообщений; для business-ответов используется с `business_connection_id`.
- `editMessageText` — перерисовка панели без лишних сообщений.
- `answerCallbackQuery` — обязательный ответ на инлайн-кнопки.
- `getBusinessConnection` — получение владельца и прав по `business_connection_id`.

## Что важно про Business Mode

- Для автоответов в бизнес-аккаунте нужен поток `business_message`.
- У входящего `business_message` есть `business_connection_id`.
- Чтобы понять владельца и права бота, можно использовать update `business_connection` и метод `getBusinessConnection`.
- Для отправки ответа нужно использовать `sendMessage` с `business_connection_id`.
- Обычный `message` и `business_message` не надо смешивать в одном runtime-потоке автоответов.

## Практические проверки

- `getWebhookInfo` должен показывать правильный `url`.
- В `allowed_updates` должны быть:
  - `business_connection`
  - `business_message`
  - `edited_business_message`
- У входящего business-сообщения должен быть `business_connection_id`.
- Если бот молчит, сначала проверить:
  - пришел ли вообще `business_message`,
  - есть ли активный сценарий у владельца connection,
  - есть ли у connection право `can_reply`.

## Лимиты и ограничения

- `callback_data` в inline-кнопках: 1-64 байта.
- Старые кнопки могут оставаться в истории, поэтому коллбеки должны быть идемпотентными.
- Business Mode и Guest Mode не следует смешивать в одном хендлере без явного разделения логики.

## Замечание по текущей реализации

- Сейчас проект использует:
  - `message` для панели и управления сценариями в личном чате с ботом
  - `business_connection` для привязки Telegram Business connection к владельцу
  - `business_message` для автоответов в бизнес-чатах
