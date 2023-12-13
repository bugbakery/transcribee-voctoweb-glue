from pydantic_settings import BaseSettings

pages = None


class Settings(BaseSettings):
    dummy: bool = False


settings = Settings()
