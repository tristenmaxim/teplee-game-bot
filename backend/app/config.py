"""App settings from environment (TECH_SPEC §9)."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str = "test:token"
    webapp_url: str = "https://example.pages.dev"
    api_public_url: str = "http://localhost:8000"
    db_path: str = "data/game.db"
    static_db_path: str = "data/game_static.db"
    data_dir: str = "data"  # en_forms.json, vectors (Этап 5)
    admin_id: int = 0
    init_data_max_age_s: int = 24 * 3600
    rate_limit_guess_per_s: float = 5.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
