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

    gemini_vision_model: str = "gemini-2.0-flash"
    gemini_vision_temperature: float = 0.4
    vision_max_image_bytes: int = 8_000_000
    vision_max_download_bytes: int = 10_000_000
    vision_max_dimension: int = 1024
    vision_jpeg_quality: int = 85
    vision_allowed_mime: list[str] = ["image/jpeg", "image/png", "image/webp"]

    history_max_messages: int = 20
    history_max_chars: int = 6000
    conversation_title_max_chars: int = 48
    conversations_max_results: int = 50

    dynamic_states_enabled: bool = True
    dynamic_states_include_humor: bool = True
