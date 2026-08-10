"""App settings from environment (TECH_SPEC §9)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str = "test:token"
    run_bot: bool = True
    webapp_url: str = "https://example.pages.dev"
    api_public_url: str = "http://localhost:8000"
    db_path: str = "data/game.db"
    static_db_path: str = "data/game_static.db"
    data_dir: str = "data"  # en_forms.json, vectors (Этап 5)
    bot_username: str = ""  # env BOT_USERNAME, for building t.me/<bot>?start=... challenge links
    init_data_max_age_s: int = 24 * 3600
    rate_limit_guess_per_s: float = 5.0
    admin_ids: str = ""  # env ADMIN_IDS, comma-separated Telegram user ids allowed into /admin
    admin_session_secret: str = ""  # env ADMIN_SESSION_SECRET; falls back to bot_token if unset


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
