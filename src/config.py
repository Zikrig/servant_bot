from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

TELEGRAM_API_BASE = "https://api.telegram.org"
EVOLINK_BASE_URL = "https://api.evolink.ai/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    telegram_bot_username: str | None = Field(default=None, alias="TELEGRAM_BOT_USERNAME")
    webhook_public_url: str = Field(alias="WEBHOOK_PUBLIC_URL")
    webhook_secret_token: str | None = Field(default=None, alias="WEBHOOK_SECRET_TOKEN")
    auto_set_webhook: bool = Field(default=True, alias="AUTO_SET_WEBHOOK")
    app_port: int = Field(default=8080, alias="APP_PORT")

    evolink_api_key: str = Field(alias="EVOLINK_API_KEY")
    evolink_model_primary: str = Field(alias="EVOLINK_MODEL_PRIMARY")
    evolink_model_fallback: str | None = Field(default=None, alias="EVOLINK_MODEL_FALLBACK")
    evolink_request_timeout_sec: int = Field(default=35, alias="EVOLINK_REQUEST_TIMEOUT_SEC")
    evolink_strict_model_validation: bool = Field(default=True, alias="EVOLINK_STRICT_MODEL_VALIDATION")

    db_path: str = Field(default="/data/bot.sqlite3", alias="DB_PATH")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    max_scenarios_per_user: int = Field(default=20, alias="MAX_SCENARIOS_PER_USER")
    max_scenario_title_len: int = Field(default=64, alias="MAX_SCENARIO_TITLE_LEN")
    max_scenario_prompt_len: int = Field(default=2000, alias="MAX_SCENARIO_PROMPT_LEN")


settings = Settings()
