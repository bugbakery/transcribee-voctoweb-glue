from pydantic_settings import BaseSettings
from pydantic_settings.main import SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    conference: str = "37c3"
    limit_events: int | None = None
    transcribee_api_url: str = "https://beta.transcribee.net"
    transcribee_pat: str = "test"

    voc_api_url: str = "https://publishing.c3voc.de/api"
    voc_token: str = "test"


settings = Settings()
