from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    # Pydantic v2 settings
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30

    # Redis (optional for local/dev)
    redis_url: Optional[str] = None

    # OpenAI (optional, we primarily use Google Gemini now)
    openai_api_key: Optional[str] = None

    # Supabase Configuration
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None

    # Google AI Configuration
    google_api_key: Optional[str] = None

    # Embeddings configuration
    # Values: 'local' (default) uses sentence-transformers; 'google' uses Google Generative AI embeddings
    embeddings_provider: str = "local"

    # External Services / Webhooks
    webhook_secret: Optional[str] = None

    # Environment
    environment: str = "development"

    # Admin Credentials (for simple admin login)
    admin_email: Optional[str] = None
    admin_password: Optional[str] = None

    # Email / SMTP configuration (optional)
    smtp_server: Optional[str] = None
    smtp_port: Optional[int] = None
    email_user: Optional[str] = None
    email_password: Optional[str] = None
    email_from_name: Optional[str] = None

    # IMAP / monitoring (optional)
    imap_server: Optional[str] = None
    imap_port: Optional[int] = None
    auto_email_response: Optional[bool] = None
    email_response_delay: Optional[int] = None


settings = Settings()
