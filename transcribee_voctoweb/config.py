from pydantic_settings import BaseSettings
from pydantic_settings.main import SettingsConfigDict

pages = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    conference: str = "37c3"
    limit_events: int | None = None


settings = Settings()
