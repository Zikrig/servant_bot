from __future__ import annotations

import aiosqlite


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

    async def list_scenarios(self, user_id: int) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            rows = await self._fetchall(
                conn,
                "SELECT * FROM scenarios WHERE user_id = ? ORDER BY created_at, id",
                (user_id,),
            )
            return [dict(row) for row in rows]

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
            return dict(row) if row else None

    async def create_scenario(self, user_id: int, title: str, system_prompt: str) -> int:
        async with aiosqlite.connect(self.db_path) as conn:
            cur = await conn.execute(
                "INSERT INTO scenarios (user_id, title, system_prompt, is_enabled) VALUES (?, ?, ?, 0)",
                (user_id, title, system_prompt),
            )
            await conn.commit()
            return int(cur.lastrowid)

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

            await conn.execute(
                "UPDATE scenarios SET is_enabled = 0 WHERE user_id = ?",
                (user_id,),
            )
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
            return dict(row) if row else None

    async def get_chat_state(self, user_id: int) -> dict:
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await self._fetchone(
                conn,
                "SELECT * FROM chat_state WHERE user_id = ?",
                (user_id,),
            )
            if row:
                return dict(row)
            await conn.execute(
                "INSERT INTO chat_state (user_id, panel_message_id, pending_action, draft_title, delete_candidate_id, selected_scenario_id) VALUES (?, NULL, NULL, NULL, NULL, NULL)",
                (user_id,),
            )
            await conn.commit()
            return {
                "user_id": user_id,
                "panel_message_id": None,
                "pending_action": None,
                "draft_title": None,
                "delete_candidate_id": None,
                "selected_scenario_id": None,
            }

    async def update_chat_state(
        self,
        user_id: int,
        *,
        panel_message_id: int | None | object = ...,
        pending_action: str | None | object = ...,
        draft_title: str | None | object = ...,
        delete_candidate_id: int | None | object = ...,
        selected_scenario_id: int | None | object = ...,
    ) -> None:
        state = await self.get_chat_state(user_id)
        payload = {
            "panel_message_id": state["panel_message_id"] if panel_message_id is ... else panel_message_id,
            "pending_action": state["pending_action"] if pending_action is ... else pending_action,
            "draft_title": state["draft_title"] if draft_title is ... else draft_title,
            "delete_candidate_id": state["delete_candidate_id"] if delete_candidate_id is ... else delete_candidate_id,
            "selected_scenario_id": state.get("selected_scenario_id") if selected_scenario_id is ... else selected_scenario_id,
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
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (
                    payload["panel_message_id"],
                    payload["pending_action"],
                    payload["draft_title"],
                    payload["delete_candidate_id"],
                    payload["selected_scenario_id"],
                    user_id,
                ),
            )
            await conn.commit()

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
            # Keep rolling history bounded per chat.
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

    async def get_recent_chat_messages(
        self,
        *,
        chat_id: int,
        limit: int = 10,
        exclude_message_id: int | None = None,
    ) -> list[dict]:
        query = """
            SELECT message_id, sender_label, text, is_bot, created_at
            FROM chat_messages
            WHERE chat_id = ?
        """
        params: tuple = (chat_id,)
        if exclude_message_id is not None:
            query += " AND (message_id IS NULL OR message_id != ?)"
            params = (chat_id, exclude_message_id)
        query += " ORDER BY id DESC LIMIT ?"
        params = (*params, limit)

        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            rows = await self._fetchall(conn, query, params)
            items = [dict(row) for row in rows]
            items.reverse()
            return items

    async def upsert_business_connection_owner(
        self,
        *,
        business_connection_id: str,
        owner_telegram_user_id: int,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO business_connections (business_connection_id, owner_telegram_user_id, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(business_connection_id) DO UPDATE SET
                    owner_telegram_user_id = excluded.owner_telegram_user_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (business_connection_id, owner_telegram_user_id),
            )
            await conn.commit()

    async def get_business_connection_owner(self, business_connection_id: str) -> int | None:
        async with aiosqlite.connect(self.db_path) as conn:
            row = await self._fetchone(
                conn,
                "SELECT owner_telegram_user_id FROM business_connections WHERE business_connection_id = ?",
                (business_connection_id,),
            )
            return int(row[0]) if row else None
