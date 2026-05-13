from __future__ import annotations

import json
from typing import Any

import aiosqlite


_MISSING = object()


class Storage:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @staticmethod
    async def _fetchone(conn: aiosqlite.Connection, query: str, params: tuple = ()) -> aiosqlite.Row | None:
        cursor = await conn.execute(query, params)
        return await cursor.fetchone()

    @staticmethod
    async def _fetchall(conn: aiosqlite.Connection, query: str, params: tuple = ()) -> list[aiosqlite.Row]:
        cursor = await conn.execute(query, params)
        return await cursor.fetchall()

    @staticmethod
    def _loads_json(raw: str | None, fallback: Any) -> Any:
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return fallback

    @staticmethod
    def _scenario_from_row(row: aiosqlite.Row | dict | None) -> dict | None:
        if row is None:
            return None
        item = dict(row)
        item["is_enabled"] = bool(item.get("is_enabled"))
        item["not_answer_twice"] = bool(item.get("not_answer_twice"))
        item["use_weekend_rules"] = bool(item.get("use_weekend_rules"))
        item["use_work_hours"] = bool(item.get("use_work_hours"))
        item["weekend_days"] = Storage._loads_json(item.get("weekend_days"), [])
        item["extra_holidays"] = Storage._loads_json(item.get("extra_holidays"), [])
        return item

    @staticmethod
    def _chat_state_from_row(row: aiosqlite.Row | dict | None, user_id: int) -> dict:
        if row is None:
            return {
                "user_id": user_id,
                "panel_message_id": None,
                "pending_action": None,
                "draft_title": None,
                "delete_candidate_id": None,
                "selected_scenario_id": None,
                "current_view": "main",
                "pending_field": None,
                "draft_data": {},
                "step_stack": [],
                "active_submenu": None,
            }
        state = dict(row)
        state["draft_data"] = Storage._loads_json(state.get("draft_data"), {})
        state["step_stack"] = Storage._loads_json(state.get("step_stack"), [])
        return state

    async def get_or_create_user(self, telegram_user_id: int) -> dict:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await self._fetchone(
                conn,
                "SELECT * FROM users WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            if row:
                return dict(row)
            cur = await conn.execute(
                "INSERT INTO users (telegram_user_id, is_active) VALUES (?, 1)",
                (telegram_user_id,),
            )
            await conn.commit()
            return {
                "id": cur.lastrowid,
                "telegram_user_id": telegram_user_id,
                "is_active": 1,
            }

    async def get_user_by_telegram_id(self, telegram_user_id: int) -> dict | None:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await self._fetchone(
                conn,
                "SELECT * FROM users WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            return dict(row) if row else None

    async def get_user_by_id(self, user_id: int) -> dict | None:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await self._fetchone(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
            return dict(row) if row else None

    async def get_users_by_telegram_ids(self, telegram_user_ids: list[int]) -> list[dict]:
        if not telegram_user_ids:
            return []
        placeholders = ",".join("?" for _ in telegram_user_ids)
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            rows = await self._fetchall(
                conn,
                f"SELECT * FROM users WHERE telegram_user_id IN ({placeholders})",
                tuple(telegram_user_ids),
            )
            return [dict(row) for row in rows]

    async def list_scenarios(self, user_id: int) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            rows = await self._fetchall(
                conn,
                "SELECT * FROM scenarios WHERE user_id = ? ORDER BY created_at, id",
                (user_id,),
            )
            return [self._scenario_from_row(row) for row in rows]

    async def count_scenarios(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as conn:
            row = await self._fetchone(
                conn,
                "SELECT COUNT(*) FROM scenarios WHERE user_id = ?",
                (user_id,),
            )
            return int(row[0])

    async def get_scenario(self, user_id: int, scenario_id: int) -> dict | None:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await self._fetchone(
                conn,
                "SELECT * FROM scenarios WHERE user_id = ? AND id = ?",
                (user_id, scenario_id),
            )
            return self._scenario_from_row(row)

    async def create_scenario(self, user_id: int, payload: dict[str, Any]) -> int:
        async with aiosqlite.connect(self.db_path) as conn:
            cur = await conn.execute(
                """
                INSERT INTO scenarios (
                    user_id,
                    title,
                    system_prompt,
                    reply_text,
                    steel_pause_minutes,
                    not_answer_twice,
                    hot_pause_minutes,
                    use_weekend_rules,
                    weekend_days,
                    extra_holidays,
                    active_day_mode,
                    use_work_hours,
                    work_start,
                    work_end,
                    template_code,
                    is_enabled
                )
                VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    user_id,
                    payload["title"],
                    payload["reply_text"],
                    payload["steel_pause_minutes"],
                    1 if payload["not_answer_twice"] else 0,
                    payload.get("hot_pause_minutes"),
                    1 if payload["use_weekend_rules"] else 0,
                    json.dumps(payload.get("weekend_days", []), ensure_ascii=False),
                    json.dumps(payload.get("extra_holidays", []), ensure_ascii=False),
                    payload["active_day_mode"],
                    1 if payload["use_work_hours"] else 0,
                    payload.get("work_start"),
                    payload.get("work_end"),
                    payload["template_code"],
                ),
            )
            await conn.commit()
            return int(cur.lastrowid)

    async def update_scenario(self, user_id: int, scenario_id: int, payload: dict[str, Any]) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            cur = await conn.execute(
                """
                UPDATE scenarios
                SET title = ?,
                    reply_text = ?,
                    steel_pause_minutes = ?,
                    not_answer_twice = ?,
                    hot_pause_minutes = ?,
                    use_weekend_rules = ?,
                    weekend_days = ?,
                    extra_holidays = ?,
                    active_day_mode = ?,
                    use_work_hours = ?,
                    work_start = ?,
                    work_end = ?,
                    template_code = ?
                WHERE user_id = ? AND id = ?
                """,
                (
                    payload["title"],
                    payload["reply_text"],
                    payload["steel_pause_minutes"],
                    1 if payload["not_answer_twice"] else 0,
                    payload.get("hot_pause_minutes"),
                    1 if payload["use_weekend_rules"] else 0,
                    json.dumps(payload.get("weekend_days", []), ensure_ascii=False),
                    json.dumps(payload.get("extra_holidays", []), ensure_ascii=False),
                    payload["active_day_mode"],
                    1 if payload["use_work_hours"] else 0,
                    payload.get("work_start"),
                    payload.get("work_end"),
                    payload["template_code"],
                    user_id,
                    scenario_id,
                ),
            )
            await conn.commit()
            return cur.rowcount > 0

    async def delete_scenario(self, user_id: int, scenario_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            cur = await conn.execute(
                "DELETE FROM scenarios WHERE user_id = ? AND id = ?",
                (user_id, scenario_id),
            )
            await conn.commit()
            return cur.rowcount > 0

    async def set_enabled_scenario(self, user_id: int, scenario_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            exists = await self._fetchone(
                conn,
                "SELECT id FROM scenarios WHERE user_id = ? AND id = ?",
                (user_id, scenario_id),
            )
            if not exists:
                await conn.rollback()
                return False
            await conn.execute("UPDATE scenarios SET is_enabled = 0 WHERE user_id = ?", (user_id,))
            await conn.execute(
                "UPDATE scenarios SET is_enabled = 1 WHERE user_id = ? AND id = ?",
                (user_id, scenario_id),
            )
            await conn.commit()
            return True

    async def disable_scenario(self, user_id: int, scenario_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as conn:
            cur = await conn.execute(
                "UPDATE scenarios SET is_enabled = 0 WHERE user_id = ? AND id = ?",
                (user_id, scenario_id),
            )
            await conn.commit()
            return cur.rowcount > 0

    async def get_enabled_scenario(self, user_id: int) -> dict | None:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await self._fetchone(
                conn,
                "SELECT * FROM scenarios WHERE user_id = ? AND is_enabled = 1 LIMIT 1",
                (user_id,),
            )
            return self._scenario_from_row(row)

    async def get_enabled_scenario_by_owner_telegram_id(self, owner_telegram_id: int) -> dict | None:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await self._fetchone(
                conn,
                """
                SELECT s.*, u.telegram_user_id AS owner_telegram_id
                FROM scenarios s
                JOIN users u ON u.id = s.user_id
                WHERE u.telegram_user_id = ? AND s.is_enabled = 1
                LIMIT 1
                """,
                (owner_telegram_id,),
            )
            return self._scenario_from_row(row)

    async def get_chat_state(self, user_id: int) -> dict:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await self._fetchone(conn, "SELECT * FROM chat_state WHERE user_id = ?", (user_id,))
            if row:
                return self._chat_state_from_row(row, user_id)
            await conn.execute(
                """
                INSERT INTO chat_state (
                    user_id,
                    panel_message_id,
                    pending_action,
                    draft_title,
                    delete_candidate_id,
                    selected_scenario_id,
                    current_view,
                    pending_field,
                    draft_data,
                    step_stack,
                    active_submenu
                )
                VALUES (?, NULL, NULL, NULL, NULL, NULL, 'main', NULL, '{}', '[]', NULL)
                """,
                (user_id,),
            )
            await conn.commit()
            return self._chat_state_from_row(None, user_id)

    async def update_chat_state(
        self,
        user_id: int,
        *,
        panel_message_id: int | None | object = _MISSING,
        pending_action: str | None | object = _MISSING,
        draft_title: str | None | object = _MISSING,
        delete_candidate_id: int | None | object = _MISSING,
        selected_scenario_id: int | None | object = _MISSING,
        current_view: str | None | object = _MISSING,
        pending_field: str | None | object = _MISSING,
        draft_data: dict[str, Any] | object = _MISSING,
        step_stack: list[str] | object = _MISSING,
        active_submenu: str | None | object = _MISSING,
    ) -> None:
        state = await self.get_chat_state(user_id)
        payload = {
            "panel_message_id": state["panel_message_id"] if panel_message_id is _MISSING else panel_message_id,
            "pending_action": state["pending_action"] if pending_action is _MISSING else pending_action,
            "draft_title": state["draft_title"] if draft_title is _MISSING else draft_title,
            "delete_candidate_id": state["delete_candidate_id"] if delete_candidate_id is _MISSING else delete_candidate_id,
            "selected_scenario_id": state["selected_scenario_id"] if selected_scenario_id is _MISSING else selected_scenario_id,
            "current_view": state["current_view"] if current_view is _MISSING else current_view,
            "pending_field": state["pending_field"] if pending_field is _MISSING else pending_field,
            "draft_data": state["draft_data"] if draft_data is _MISSING else draft_data,
            "step_stack": state["step_stack"] if step_stack is _MISSING else step_stack,
            "active_submenu": state["active_submenu"] if active_submenu is _MISSING else active_submenu,
        }
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                UPDATE chat_state
                SET panel_message_id = ?,
                    pending_action = ?,
                    draft_title = ?,
                    delete_candidate_id = ?,
                    selected_scenario_id = ?,
                    current_view = ?,
                    pending_field = ?,
                    draft_data = ?,
                    step_stack = ?,
                    active_submenu = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (
                    payload["panel_message_id"],
                    payload["pending_action"],
                    payload["draft_title"],
                    payload["delete_candidate_id"],
                    payload["selected_scenario_id"],
                    payload["current_view"],
                    payload["pending_field"],
                    json.dumps(payload["draft_data"], ensure_ascii=False),
                    json.dumps(payload["step_stack"], ensure_ascii=False),
                    payload["active_submenu"],
                    user_id,
                ),
            )
            await conn.commit()

    async def upsert_managed_chat(
        self,
        *,
        chat_id: int,
        owner_user_id: int,
        owner_telegram_id: int,
        title: str | None,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO managed_chats (chat_id, owner_user_id, owner_telegram_id, title, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id) DO UPDATE SET
                    owner_user_id = excluded.owner_user_id,
                    owner_telegram_id = excluded.owner_telegram_id,
                    title = excluded.title,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (chat_id, owner_user_id, owner_telegram_id, title),
            )
            await conn.commit()

    async def get_managed_chat(self, chat_id: int) -> dict | None:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await self._fetchone(conn, "SELECT * FROM managed_chats WHERE chat_id = ?", (chat_id,))
            return dict(row) if row else None

    async def upsert_business_connection(
        self,
        *,
        business_connection_id: str,
        owner_user_id: int,
        owner_telegram_id: int,
        owner_private_chat_id: int | None,
        can_reply: bool,
        can_read_messages: bool,
        raw_rights: dict[str, Any] | None,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            columns = {
                row[1]
                for row in await (await conn.execute("PRAGMA table_info(business_connections)")).fetchall()
            }
            insert_columns = [
                "business_connection_id",
                "owner_user_id",
                "owner_telegram_id",
                "owner_private_chat_id",
                "can_reply",
                "can_read_messages",
                "raw_rights",
                "updated_at",
            ]
            insert_values: list[Any] = [
                business_connection_id,
                owner_user_id,
                owner_telegram_id,
                owner_private_chat_id,
                1 if can_reply else 0,
                1 if can_read_messages else 0,
                json.dumps(raw_rights or {}, ensure_ascii=False),
                "CURRENT_TIMESTAMP",
            ]
            update_assignments = [
                "owner_user_id = excluded.owner_user_id",
                "owner_telegram_id = excluded.owner_telegram_id",
                "owner_private_chat_id = excluded.owner_private_chat_id",
                "can_reply = excluded.can_reply",
                "can_read_messages = excluded.can_read_messages",
                "raw_rights = excluded.raw_rights",
                "updated_at = CURRENT_TIMESTAMP",
            ]
            if "owner_telegram_user_id" in columns:
                insert_columns.insert(3, "owner_telegram_user_id")
                insert_values.insert(3, owner_telegram_id)
                update_assignments.insert(2, "owner_telegram_user_id = excluded.owner_telegram_user_id")

            placeholders = ", ".join("?" if value != "CURRENT_TIMESTAMP" else "CURRENT_TIMESTAMP" for value in insert_values)
            parameters = tuple(value for value in insert_values if value != "CURRENT_TIMESTAMP")
            await conn.execute(
                f"""
                INSERT INTO business_connections ({", ".join(insert_columns)})
                VALUES ({placeholders})
                ON CONFLICT(business_connection_id) DO UPDATE SET
                    {", ".join(update_assignments)}
                """,
                parameters,
            )
            await conn.commit()

    async def get_business_connection(self, business_connection_id: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await self._fetchone(
                conn,
                "SELECT * FROM business_connections WHERE business_connection_id = ?",
                (business_connection_id,),
            )
            if not row:
                return None
            item = dict(row)
            if item.get("owner_telegram_id") is None and item.get("owner_telegram_user_id") is not None:
                item["owner_telegram_id"] = item["owner_telegram_user_id"]
            item["can_reply"] = bool(item.get("can_reply"))
            item["can_read_messages"] = bool(item.get("can_read_messages"))
            item["raw_rights"] = self._loads_json(item.get("raw_rights"), {})
            return item

    async def get_conversation_state(self, chat_id: int, owner_user_id: int) -> dict | None:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await self._fetchone(
                conn,
                "SELECT * FROM conversation_state WHERE chat_id = ? AND owner_user_id = ?",
                (chat_id, owner_user_id),
            )
            return dict(row) if row else None

    async def schedule_conversation_reply(
        self,
        *,
        chat_id: int,
        owner_user_id: int,
        scenario_id: int,
        business_connection_id: str | None,
        due_at: str,
        message_id: int | None,
        customer_message_at: str,
    ) -> None:
        current = await self.get_conversation_state(chat_id, owner_user_id)
        last_owner_message_at = current.get("last_owner_message_at") if current else None
        last_bot_reply_at = current.get("last_bot_reply_at") if current else None
        last_bot_reply_message_id = current.get("last_bot_reply_message_id") if current else None
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO conversation_state (
                    chat_id,
                    owner_user_id,
                    scenario_id,
                    business_connection_id,
                    waiting_due_at,
                    waiting_from_message_id,
                    last_customer_message_at,
                    last_owner_message_at,
                    last_bot_reply_at,
                    last_bot_reply_message_id,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id, owner_user_id) DO UPDATE SET
                    scenario_id = excluded.scenario_id,
                    business_connection_id = excluded.business_connection_id,
                    waiting_due_at = excluded.waiting_due_at,
                    waiting_from_message_id = excluded.waiting_from_message_id,
                    last_customer_message_at = excluded.last_customer_message_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    chat_id,
                    owner_user_id,
                    scenario_id,
                    business_connection_id,
                    due_at,
                    message_id,
                    customer_message_at,
                    last_owner_message_at,
                    last_bot_reply_at,
                    last_bot_reply_message_id,
                ),
            )
            await conn.commit()

    async def mark_owner_activity(self, *, chat_id: int, owner_user_id: int, owner_message_at: str) -> None:
        current = await self.get_conversation_state(chat_id, owner_user_id)
        scenario_id = current.get("scenario_id") if current else 0
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO conversation_state (
                    chat_id,
                    owner_user_id,
                    scenario_id,
                    business_connection_id,
                    waiting_due_at,
                    last_owner_message_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, NULL, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id, owner_user_id) DO UPDATE SET
                    waiting_due_at = NULL,
                    last_owner_message_at = excluded.last_owner_message_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (chat_id, owner_user_id, scenario_id, current.get("business_connection_id") if current else None, owner_message_at),
            )
            await conn.commit()

    async def mark_bot_replied(
        self,
        *,
        chat_id: int,
        owner_user_id: int,
        replied_at: str,
        message_id: int | None,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                UPDATE conversation_state
                SET waiting_due_at = NULL,
                    last_bot_reply_at = ?,
                    last_bot_reply_message_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE chat_id = ? AND owner_user_id = ?
                """,
                (replied_at, message_id, chat_id, owner_user_id),
            )
            await conn.commit()

    async def clear_waiting_reply(self, *, chat_id: int, owner_user_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                UPDATE conversation_state
                SET waiting_due_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE chat_id = ? AND owner_user_id = ?
                """,
                (chat_id, owner_user_id),
            )
            await conn.commit()

    async def list_due_conversations(self, now_iso: str) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            rows = await self._fetchall(
                conn,
                """
                SELECT cs.*, s.title, s.reply_text, s.steel_pause_minutes, s.not_answer_twice,
                       s.hot_pause_minutes, s.use_weekend_rules, s.weekend_days, s.extra_holidays,
                       s.active_day_mode, s.use_work_hours, s.work_start, s.work_end, s.template_code,
                       s.is_enabled, u.telegram_user_id AS owner_telegram_id
                FROM conversation_state cs
                JOIN scenarios s ON s.id = cs.scenario_id
                JOIN users u ON u.id = cs.owner_user_id
                WHERE cs.waiting_due_at IS NOT NULL
                  AND cs.waiting_due_at <= ?
                  AND s.is_enabled = 1
                ORDER BY cs.waiting_due_at ASC
                """,
                (now_iso,),
            )
            result: list[dict] = []
            for row in rows:
                item = dict(row)
                item["not_answer_twice"] = bool(item.get("not_answer_twice"))
                item["use_weekend_rules"] = bool(item.get("use_weekend_rules"))
                item["use_work_hours"] = bool(item.get("use_work_hours"))
                item["is_enabled"] = bool(item.get("is_enabled"))
                item["weekend_days"] = self._loads_json(item.get("weekend_days"), [])
                item["extra_holidays"] = self._loads_json(item.get("extra_holidays"), [])
                result.append(item)
            return result

    async def append_chat_message(
        self,
        *,
        chat_id: int,
        message_id: int | None,
        sender_label: str,
        text: str,
        is_bot: bool,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO chat_messages (chat_id, message_id, sender_label, text, is_bot)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chat_id, message_id, sender_label, text, 1 if is_bot else 0),
            )
            await conn.execute(
                """
                DELETE FROM chat_messages
                WHERE chat_id = ?
                  AND id NOT IN (
                      SELECT id
                      FROM chat_messages
                      WHERE chat_id = ?
                      ORDER BY id DESC
                      LIMIT 200
                  )
                """,
                (chat_id, chat_id),
            )
            await conn.commit()

