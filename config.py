from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_chat_id: int
    db_path: str


def load_settings() -> Settings:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    admin_chat_raw = os.getenv("ADMIN_CHAT_ID", "").strip()
    db_path = os.getenv("DB_PATH", "bot_data.db").strip() or "bot_data.db"

    if not bot_token:
        raise ValueError("BOT_TOKEN is missing. Put it in your .env file.")
    if not admin_chat_raw:
        raise ValueError("ADMIN_CHAT_ID is missing. Put it in your .env file.")

    try:
        admin_chat_id = int(admin_chat_raw)
    except ValueError as exc:
        raise ValueError("ADMIN_CHAT_ID must be a number.") from exc

    return Settings(bot_token=bot_token, admin_chat_id=admin_chat_id, db_path=db_path)
