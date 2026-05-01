from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    telegram_token: str
    openai_api_key: str
    google_spreadsheet_id: str
    google_credentials_json: str = "credentials.json"
    allowed_user_id: int


settings = Settings()
