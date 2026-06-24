"""Application configuration via environment / .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings

_env_path = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # server
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = True

    # data
    default_history_period: str = "5y"  # 1y / 2y / 5y / max
    db_path: str = str(Path(__file__).resolve().parent.parent / "data" / "stocks.db")

    # llm defaults
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2000

    model_config = {"env_file": str(_env_path), "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
