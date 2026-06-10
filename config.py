# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/config.py

import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Telegram Bot Settings
    TELEGRAM_BOT_TOKEN: Optional[str] = None

    # Notion API Settings
    NOTION_API_KEY: str = ""

    # Notion Database IDs
    DATABASE_ID_ACTIVITY_LOG: str = "placeholder_activity_log"
    DATABASE_ID_FINANCIAL_LOG: str = "placeholder_financial_log"
    DATABASE_ID_DIET_LOG: str = "placeholder_diet_log"
    DATABASE_ID_SUBJECTIVE_JOURNAL: str = "placeholder_subjective_journal"
    DATABASE_ID_RELATIONAL_JOURNAL: str = "placeholder_relational_journal"
    DATABASE_ID_SYSTEMIC_JOURNAL: str = "placeholder_systemic_journal"

    # Cache Configuration
    CACHE_DIR: str = os.path.expanduser("~/.cache/lifeos_bot")
    CACHE_DEFAULT_TTL: int = 300  # 5 minutes in seconds
    CACHE_STATIC_TTL: int = 86400  # 24 hours in seconds for select options

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Module-level singleton — use reload_settings() after discovery updates .env
settings = Settings()

def reload_settings() -> Settings:
    """Re-reads .env and updates the existing settings object in-place.
    This ensures all modules that imported `settings` see the new values
    without needing to re-import.
    """
    fresh = Settings()
    for field in Settings.model_fields:
        setattr(settings, field, getattr(fresh, field))
    return settings
