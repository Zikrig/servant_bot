from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

TELEGRAM_API_BASE = "https://api.telegram.org"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    telegram_bot_username: str | None = Field(default=None, alias="TELEGRAM_BOT_USERNAME")
    webhook_public_url: str = Field(alias="WEBHOOK_PUBLIC_URL")
    webhook_secret_token: str | None = Field(default=None, alias="WEBHOOK_SECRET_TOKEN")
    auto_set_webhook: bool = Field(default=True, alias="AUTO_SET_WEBHOOK")
    app_port: int = Field(default=8080, alias="APP_PORT")

    db_path: str = Field(default="/data/bot.sqlite3", alias="DB_PATH")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    max_scenarios_per_user: int = Field(default=20, alias="MAX_SCENARIOS_PER_USER")
    max_scenario_title_len: int = Field(default=64, alias="MAX_SCENARIO_TITLE_LEN")
    max_scenario_reply_len: int = Field(default=4000, alias="MAX_SCENARIO_REPLY_LEN")
    scheduler_poll_seconds: int = Field(default=15, alias="SCHEDULER_POLL_SECONDS")


settings = Settings()
