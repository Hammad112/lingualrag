from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    APP_NAME: str = "LingualRAG"
    APP_ENV: str = "development"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    SECRET_KEY: str = "change-me"
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    DATABASE_URL: str = "sqlite+aiosqlite:///./lingualrag.db"

    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""

    QDRANT_URL: str = ""
    QDRANT_API_KEY: str = ""
    QDRANT_PATH: str = "./qdrant_data"
    QDRANT_COLLECTION: str = "lingualrag_chunks"

    EMBEDDING_MODEL: str = "gemini-embedding-001"
    EMBEDDING_DIM: int = 768
    GEMINI_API_KEY: str = ""
    HF_API_TOKEN: str = ""

    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # When true, uploaded files are processed in-memory and never written to disk.
    # Recommended for ephemeral-fs hosts like Render free tier.
    PERSIST_UPLOADS: bool = True

    TOP_K_DENSE: int = 20
    TOP_K_FINAL: int = 5
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 80

    OTP_LENGTH: int = 6
    OTP_EXPIRE_MINUTES: int = 10
    OTP_PRINT_TO_CONSOLE: bool = True

    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@lingualrag.local"

    STORAGE_DIR: str = "./storage"

    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:3000"]
    BACKEND_CORS_ORIGIN_REGEX: str = ""

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [s.strip() for s in v.split(",") if s.strip()]
        return v


settings = Settings()
