from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./agro.db"
    secret_key: str = "dev-secret-key"
    debug: bool = True

    # Ollama (local vision model — photo validation gate)
    ollama_url: str = "http://192.168.10.40:11434"

    # External CV service
    plant_id_api_key: str = ""

    # LLM for explanation layer
    openai_api_key: str = ""

    # Weather
    weather_api_key: str = ""

    # Video pipeline
    video_pipeline_url: str = ""
    video_pipeline_api_key: str = ""

    # Billing
    billing_service_url: str = ""
    billing_service_api_key: str = ""

    # S3
    s3_endpoint: str = ""
    s3_bucket: str = "agro-media"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # CORS (comma-separated origins; extend via env var ALLOWED_ORIGINS)
    allowed_origins: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "https://agro-ai-frontend-kohl.vercel.app"
    )

    # Scoring
    top_issues_count: int = 3
    min_score_threshold: float = 0.05

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
