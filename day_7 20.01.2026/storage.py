"""
User Preferences Storage Module

Provides persistent storage for user preferences using SQLite.
Handles database initialization, user model preferences, and cleanup.
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Database file path (in the same directory as the bot)
DB_PATH = Path(__file__).parent / "user_preferences.db"


def init_database() -> None:
    """Initialize the database and create tables if they don't exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER PRIMARY KEY,
                selected_model TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    logger.info(f"Database initialized at {DB_PATH}")


@contextmanager
def get_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def get_user_model(user_id: int) -> Optional[str]:
    """
    Get the selected model for a user.

    Args:
        user_id: Telegram user ID

    Returns:
        Model ID string or None if not set
    """
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT selected_model FROM user_preferences WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else None


def set_user_model(user_id: int, model_id: str) -> None:
    """
    Set the selected model for a user.

    Args:
        user_id: Telegram user ID
        model_id: OpenAI model ID to set
    """
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO user_preferences (user_id, selected_model, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                selected_model = excluded.selected_model,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, model_id))
        conn.commit()
    logger.info(f"User {user_id} model set to {model_id}")


def delete_user_preference(user_id: int) -> bool:
    """
    Delete user's model preference.

    Args:
        user_id: Telegram user ID

    Returns:
        True if preference was deleted, False if not found
    """
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM user_preferences WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
