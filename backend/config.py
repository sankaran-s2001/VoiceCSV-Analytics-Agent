"""Configuration management for VoiceCSV Analytics Agent."""

import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

# Locate project root directory relative to this file
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
ENV_PATH = PROJECT_ROOT / ".env"

# Load environment variables if .env exists
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()  # Fallback to system env or default lookup


@dataclass
class Settings:
    """Application settings with strong defaults and safe overrides."""
    
    # API configuration
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "").strip()
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    
    # Database configuration
    sqlite_db_path: str = os.getenv("SQLITE_DB_PATH", "data/analytics.db").strip()
    
    # Server configuration
    host: str = os.getenv("HOST", "127.0.0.1").strip()
    port: int = int(os.getenv("PORT", "8000").strip() or "8000")
    
    # Operational constraints
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "100").strip() or "100")
    max_query_rows: int = int(os.getenv("MAX_QUERY_ROWS", "500").strip() or "500")
    query_timeout_seconds: int = int(os.getenv("QUERY_TIMEOUT_SECONDS", "10").strip() or "10")
    gemini_max_retries: int = int(os.getenv("GEMINI_MAX_RETRIES", "4").strip() or "4")
    gemini_max_repairs: int = int(os.getenv("GEMINI_MAX_REPAIRS", "3").strip() or "3")
    gemini_requests_per_minute: int = int(os.getenv("GEMINI_REQUESTS_PER_MINUTE", "15").strip() or "15")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def data_dir(self) -> Path:
        """Get absolute path to data directory, ensuring it exists."""
        d = PROJECT_ROOT / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def resolved_db_path(self) -> Path:
        """Get absolute path to SQLite database, ensuring parent directory exists."""
        p = Path(self.sqlite_db_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def is_gemini_configured(self) -> bool:
        """Return True if a valid-looking Google API key is configured."""
        if not self.google_api_key:
            return False
        if self.google_api_key in (
            "your_google_ai_studio_api_key",
            "your_api_key_here",
            "your_actual_api_key_here",
            "your_gemini_api_key_here",
        ):
            return False
        return len(self.google_api_key) > 5

    def safe_dict(self) -> dict:
        """Return configuration dict without exposing secret API keys."""
        return {
            "gemini_model": self.gemini_model,
            "sqlite_db_path": self.sqlite_db_path,
            "host": self.host,
            "port": self.port,
            "max_upload_mb": self.max_upload_mb,
            "max_query_rows": self.max_query_rows,
            "query_timeout_seconds": self.query_timeout_seconds,
            "gemini_max_retries": self.gemini_max_retries,
            "gemini_max_repairs": self.gemini_max_repairs,
            "gemini_requests_per_minute": self.gemini_requests_per_minute,
            "is_gemini_configured": self.is_gemini_configured,
        }


# Global settings instance
settings = Settings()
