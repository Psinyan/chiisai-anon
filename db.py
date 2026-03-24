from __future__ import annotations

import random
import sqlite3
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_anon_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "A" + "".join(random.choice(alphabet) for _ in range(7))


@dataclass
class OutboundTarget:
    user_id: int
    anon_id: str


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    anon_id TEXT NOT NULL UNIQUE,
                    is_banned INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS message_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    admin_message_id INTEGER NOT NULL UNIQUE,
                    user_message_id INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outbound_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    anon_id TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    sent_at TEXT NOT NULL,
                    UNIQUE(chat_id, message_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_message_links_admin_message_id
                ON message_links(admin_message_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_users_anon_id
                ON users(anon_id)
                """
            )

    def get_or_create_user(self, telegram_user_id: int) -> sqlite3.Row:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()
            if row:
                return row

            anon_id = self._new_unique_anon_id(conn)
            conn.execute(
                """
                INSERT INTO users (telegram_user_id, anon_id, is_banned, created_at)
                VALUES (?, ?, 0, ?)
                """,
                (telegram_user_id, anon_id, utc_now_iso()),
            )
            return conn.execute(
                "SELECT * FROM users WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()

    def _new_unique_anon_id(self, conn: sqlite3.Connection) -> str:
        while True:
            candidate = create_anon_id()
            exists = conn.execute(
                "SELECT 1 FROM users WHERE anon_id = ?",
                (candidate,),
            ).fetchone()
            if not exists:
                return candidate

    def is_banned(self, telegram_user_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT is_banned FROM users WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()
            return bool(row and row["is_banned"])

    def set_ban(self, anon_id: str, is_banned: bool) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE users SET is_banned = ? WHERE anon_id = ?",
                (1 if is_banned else 0, anon_id.strip().upper()),
            )
            return result.rowcount > 0

    def get_user_by_anon_id(self, anon_id: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE anon_id = ?",
                (anon_id.strip().upper(),),
            ).fetchone()

    def save_message_link(
        self,
        *,
        user_id: int,
        admin_message_id: int,
        user_message_id: int,
        direction: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO message_links
                (user_id, admin_message_id, user_message_id, direction, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, admin_message_id, user_message_id, direction, utc_now_iso()),
            )

    def get_target_by_admin_message_id(self, admin_message_id: int) -> Optional[OutboundTarget]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT ml.user_id, u.anon_id
                FROM message_links ml
                JOIN users u ON u.telegram_user_id = ml.user_id
                WHERE ml.admin_message_id = ?
                """,
                (admin_message_id,),
            ).fetchone()
            if not row:
                return None
            return OutboundTarget(user_id=int(row["user_id"]), anon_id=str(row["anon_id"]))

    def save_outbound_message(self, *, user_id: int, anon_id: str, chat_id: int, message_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO outbound_messages
                (user_id, anon_id, chat_id, message_id, sent_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, anon_id, chat_id, message_id, utc_now_iso()),
            )

    def find_outbound_message(self, *, chat_id: int, message_id: int) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT user_id, anon_id, chat_id, message_id, sent_at
                FROM outbound_messages
                WHERE chat_id = ? AND message_id = ?
                """,
                (chat_id, message_id),
            ).fetchone()

    def get_admin_message_for_outbound_dm(
        self, *, user_id: int, user_message_id: int
    ) -> Optional[int]:
        """admin_to_user link: bot DM message_id -> admin chat message_id."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT admin_message_id FROM message_links
                WHERE user_id = ? AND user_message_id = ? AND direction = 'admin_to_user'
                """,
                (user_id, user_message_id),
            ).fetchone()
            return int(row["admin_message_id"]) if row else None

    def get_user_dm_for_admin_forward(self, admin_message_id: int) -> Optional[tuple[int, int]]:
        """user_to_admin link: forwarded message in admin chat -> user's private message."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT user_id, user_message_id FROM message_links
                WHERE admin_message_id = ? AND direction = 'user_to_admin'
                """,
                (admin_message_id,),
            ).fetchone()
            if not row:
                return None
            return (int(row["user_id"]), int(row["user_message_id"]))

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            users_count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
            banned_count = conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_banned = 1").fetchone()["c"]
            messages_count = conn.execute("SELECT COUNT(*) AS c FROM message_links").fetchone()["c"]
            outbound_count = conn.execute("SELECT COUNT(*) AS c FROM outbound_messages").fetchone()["c"]
            return {
                "users": int(users_count),
                "banned": int(banned_count),
                "linked_messages": int(messages_count),
                "outbound_messages": int(outbound_count),
            }
