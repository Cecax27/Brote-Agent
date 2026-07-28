from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    gemini_api_key: str
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_temperature: float = 0.7
    gemini_max_output_tokens: int = 1024
    port: int = 8080
    log_level: str = "INFO"

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    context_max_plants: int = 20
    context_max_recent_entries: int = 10

    action_signing_secret: str = ""
    action_token_ttl_seconds: int = 300
