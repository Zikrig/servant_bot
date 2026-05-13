import aiosqlite


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    reply_text TEXT NOT NULL DEFAULT '',
    steel_pause_minutes INTEGER NOT NULL DEFAULT 5,
    not_answer_twice INTEGER NOT NULL DEFAULT 1,
    hot_pause_minutes INTEGER,
    use_weekend_rules INTEGER NOT NULL DEFAULT 0,
    weekend_days TEXT NOT NULL DEFAULT '[]',
    extra_holidays TEXT NOT NULL DEFAULT '[]',
    active_day_mode TEXT NOT NULL DEFAULT 'always',
    use_work_hours INTEGER NOT NULL DEFAULT 0,
    work_start TEXT,
    work_end TEXT,
    template_code TEXT NOT NULL DEFAULT 'custom',
    is_enabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_enabled_scenario_per_user
ON scenarios(user_id)
WHERE is_enabled = 1;

CREATE TABLE IF NOT EXISTS chat_state (
    user_id INTEGER PRIMARY KEY,
    panel_message_id INTEGER,
    pending_action TEXT,
    draft_title TEXT,
    delete_candidate_id INTEGER,
    selected_scenario_id INTEGER,
    current_view TEXT NOT NULL DEFAULT 'main',
    pending_field TEXT,
    draft_data TEXT NOT NULL DEFAULT '{}',
    step_stack TEXT NOT NULL DEFAULT '[]',
    active_submenu TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS managed_chats (
    chat_id INTEGER PRIMARY KEY,
    owner_user_id INTEGER NOT NULL,
    owner_telegram_id INTEGER NOT NULL,
    title TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS conversation_state (
    chat_id INTEGER NOT NULL,
    owner_user_id INTEGER NOT NULL,
    scenario_id INTEGER NOT NULL,
    waiting_due_at TEXT,
    waiting_from_message_id INTEGER,
    last_customer_message_at TEXT,
    last_owner_message_at TEXT,
    last_bot_reply_at TEXT,
    last_bot_reply_message_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, owner_user_id),
    FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    message_id INTEGER,
    sender_label TEXT NOT NULL,
    text TEXT NOT NULL,
    is_bot INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id_id
ON chat_messages(chat_id, id DESC);
"""


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(SCHEMA_SQL)

        async def ensure_column(table: str, column: str, ddl: str) -> None:
            columns = {
                row[1]
                for row in await (await conn.execute(f"PRAGMA table_info({table})")).fetchall()
            }
            if column not in columns:
                await conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

        await ensure_column("chat_state", "selected_scenario_id", "selected_scenario_id INTEGER")
        await ensure_column("chat_state", "current_view", "current_view TEXT NOT NULL DEFAULT 'main'")
        await ensure_column("chat_state", "pending_field", "pending_field TEXT")
        await ensure_column("chat_state", "draft_data", "draft_data TEXT NOT NULL DEFAULT '{}'")
        await ensure_column("chat_state", "step_stack", "step_stack TEXT NOT NULL DEFAULT '[]'")
        await ensure_column("chat_state", "active_submenu", "active_submenu TEXT")

        await ensure_column("scenarios", "reply_text", "reply_text TEXT NOT NULL DEFAULT ''")
        await ensure_column("scenarios", "steel_pause_minutes", "steel_pause_minutes INTEGER NOT NULL DEFAULT 5")
        await ensure_column("scenarios", "not_answer_twice", "not_answer_twice INTEGER NOT NULL DEFAULT 1")
        await ensure_column("scenarios", "hot_pause_minutes", "hot_pause_minutes INTEGER")
        await ensure_column("scenarios", "use_weekend_rules", "use_weekend_rules INTEGER NOT NULL DEFAULT 0")
        await ensure_column("scenarios", "weekend_days", "weekend_days TEXT NOT NULL DEFAULT '[]'")
        await ensure_column("scenarios", "extra_holidays", "extra_holidays TEXT NOT NULL DEFAULT '[]'")
        await ensure_column("scenarios", "active_day_mode", "active_day_mode TEXT NOT NULL DEFAULT 'always'")
        await ensure_column("scenarios", "use_work_hours", "use_work_hours INTEGER NOT NULL DEFAULT 0")
        await ensure_column("scenarios", "work_start", "work_start TEXT")
        await ensure_column("scenarios", "work_end", "work_end TEXT")
        await ensure_column("scenarios", "template_code", "template_code TEXT NOT NULL DEFAULT 'custom'")

        await conn.commit()
