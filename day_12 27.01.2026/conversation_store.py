"""
Conversation Storage Module

Provides persistent storage for user conversation history, summaries,
and summary configuration. Uses SQLite for data persistence.

Message counting policy: counts user+assistant turn pairs (a "message" = 1 user + 1 assistant).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import contextmanager
from dataclasses import dataclass, asdict

import sqlite3

logger = logging.getLogger(__name__)

# Database file path (in the same directory as the bot)
CONVERSATION_DB_PATH = Path(__file__).parent / "conversations.db"


@dataclass
class SummaryConfig:
    """User's summary configuration."""
    enabled: bool
    message_threshold: int  # N - number of messages before summarization

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SummaryConfig":
        return cls(
            enabled=data.get("enabled", False),
            message_threshold=data.get("message_threshold", 10)
        )


@dataclass
class ConversationState:
    """User's conversation state."""
    user_id: int
    messages: list[dict]  # List of {"role": str, "content": str}
    summary: Optional[str]  # Current summary text
    message_count: int  # Messages since last compression
    summary_config: SummaryConfig
    last_summary_at: Optional[datetime]

    def get_context_for_openai(self, system_prompt: str) -> list[dict]:
        """
        Build message list for OpenAI API.

        Returns:
            List of messages including system prompt, summary (if exists),
            and recent messages.
        """
        context = [{"role": "system", "content": system_prompt}]

        # Add summary as context if exists
        if self.summary:
            context.append({
                "role": "system",
                "content": f"Conversation summary so far:\n{self.summary}"
            })

        # Add recent messages
        context.extend(self.messages)

        return context


class ConversationStore:
    """
    Manages persistent conversation storage for all users.

    Each user has their own conversation history, summary, and configuration.
    """

    MIN_MESSAGE_THRESHOLD = 1
    MAX_MESSAGE_THRESHOLD = 500
    DEFAULT_MESSAGE_THRESHOLD = 10

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or CONVERSATION_DB_PATH
        self._init_database()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_database(self) -> None:
        """Initialize database tables."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    user_id INTEGER PRIMARY KEY,
                    messages TEXT NOT NULL DEFAULT '[]',
                    summary TEXT,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    last_summary_at TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS summary_config (
                    user_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    message_threshold INTEGER NOT NULL DEFAULT 10,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        logger.info(f"Conversation database initialized at {self.db_path}")

    def get_conversation_state(self, user_id: int) -> ConversationState:
        """
        Get or create conversation state for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            ConversationState with all user's conversation data
        """
        with self._get_connection() as conn:
            # Get conversation history
            cursor = conn.execute(
                "SELECT messages, summary, message_count, last_summary_at "
                "FROM conversation_history WHERE user_id = ?",
                (user_id,)
            )
            history_row = cursor.fetchone()

            # Get summary config
            cursor = conn.execute(
                "SELECT enabled, message_threshold "
                "FROM summary_config WHERE user_id = ?",
                (user_id,)
            )
            config_row = cursor.fetchone()

        # Parse history data
        if history_row:
            messages = json.loads(history_row["messages"])
            summary = history_row["summary"]
            message_count = history_row["message_count"]
            last_summary_at_str = history_row["last_summary_at"]
            last_summary_at = (
                datetime.fromisoformat(last_summary_at_str)
                if last_summary_at_str else None
            )
        else:
            messages = []
            summary = None
            message_count = 0
            last_summary_at = None

        # Parse config data
        if config_row:
            summary_config = SummaryConfig(
                enabled=config_row["enabled"] == 1,
                message_threshold=config_row["message_threshold"]
            )
        else:
            summary_config = SummaryConfig(
                enabled=False,
                message_threshold=self.DEFAULT_MESSAGE_THRESHOLD
            )

        return ConversationState(
            user_id=user_id,
            messages=messages,
            summary=summary,
            message_count=message_count,
            summary_config=summary_config,
            last_summary_at=last_summary_at
        )

    def add_message(self, user_id: int, role: str, content: str) -> ConversationState:
        """
        Add a message to user's conversation history.

        Args:
            user_id: Telegram user ID
            role: Message role ("user" or "assistant")
            content: Message content

        Returns:
            Updated ConversationState
        """
        state = self.get_conversation_state(user_id)
        state.messages.append({"role": role, "content": content})

        # Increment message count only when we complete a user+assistant pair
        if role == "assistant":
            state.message_count += 1

        self._save_conversation_history(state)
        return state

    def _save_conversation_history(self, state: ConversationState) -> None:
        """Save conversation history to database."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO conversation_history
                    (user_id, messages, summary, message_count, last_summary_at, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    messages = excluded.messages,
                    summary = excluded.summary,
                    message_count = excluded.message_count,
                    last_summary_at = excluded.last_summary_at,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                state.user_id,
                json.dumps(state.messages, ensure_ascii=False),
                state.summary,
                state.message_count,
                state.last_summary_at.isoformat() if state.last_summary_at else None
            ))
            conn.commit()

    def get_summary_config(self, user_id: int) -> SummaryConfig:
        """Get user's summary configuration."""
        state = self.get_conversation_state(user_id)
        return state.summary_config

    def set_summary_config(
        self,
        user_id: int,
        enabled: Optional[bool] = None,
        message_threshold: Optional[int] = None
    ) -> SummaryConfig:
        """
        Update user's summary configuration.

        Args:
            user_id: Telegram user ID
            enabled: Whether summarization is enabled
            message_threshold: Number of messages before summarization (N)

        Returns:
            Updated SummaryConfig
        """
        current = self.get_summary_config(user_id)

        if enabled is not None:
            current.enabled = enabled
        if message_threshold is not None:
            # Validate threshold
            if message_threshold < self.MIN_MESSAGE_THRESHOLD:
                message_threshold = self.MIN_MESSAGE_THRESHOLD
            elif message_threshold > self.MAX_MESSAGE_THRESHOLD:
                message_threshold = self.MAX_MESSAGE_THRESHOLD
            current.message_threshold = message_threshold

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO summary_config (user_id, enabled, message_threshold, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    message_threshold = excluded.message_threshold,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, 1 if current.enabled else 0, current.message_threshold))
            conn.commit()

        logger.info(
            f"User {user_id} summary config updated: "
            f"enabled={current.enabled}, threshold={current.message_threshold}"
        )
        return current

    def apply_summary(
        self,
        user_id: int,
        summary: str,
        keep_last_n_messages: int = 2
    ) -> ConversationState:
        """
        Apply a summary to user's conversation, replacing old messages.

        Args:
            user_id: Telegram user ID
            summary: The generated summary text
            keep_last_n_messages: Number of recent messages to keep for continuity

        Returns:
            Updated ConversationState
        """
        state = self.get_conversation_state(user_id)

        # Keep last N messages (user+assistant pairs = N*2 individual messages)
        messages_to_keep = keep_last_n_messages * 2
        if len(state.messages) > messages_to_keep:
            state.messages = state.messages[-messages_to_keep:]

        # Update summary (append to existing if there was one)
        if state.summary:
            state.summary = f"{state.summary}\n\n---\n\n{summary}"
        else:
            state.summary = summary

        # Reset message counter
        state.message_count = 0
        state.last_summary_at = datetime.now()

        self._save_conversation_history(state)

        logger.info(
            f"Summary applied for user {user_id}: "
            f"kept {len(state.messages)} messages, reset counter"
        )
        return state

    def should_summarize(self, user_id: int) -> bool:
        """
        Check if summarization should be triggered for user.

        Args:
            user_id: Telegram user ID

        Returns:
            True if message count has reached threshold and summarization is enabled
        """
        state = self.get_conversation_state(user_id)
        return (
            state.summary_config.enabled and
            state.message_count >= state.summary_config.message_threshold
        )

    def get_messages_for_summarization(self, user_id: int) -> list[dict]:
        """
        Get messages that need to be summarized.

        Returns only messages since last summary (not including retained messages).

        Args:
            user_id: Telegram user ID

        Returns:
            List of messages to summarize
        """
        state = self.get_conversation_state(user_id)
        return state.messages.copy()

    def clear_conversation(self, user_id: int) -> None:
        """
        Clear all conversation data for a user.

        Args:
            user_id: Telegram user ID
        """
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM conversation_history WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()
        logger.info(f"Conversation cleared for user {user_id}")

    def get_message_count(self, user_id: int) -> int:
        """Get current message count since last compression."""
        state = self.get_conversation_state(user_id)
        return state.message_count

    def get_total_messages(self, user_id: int) -> int:
        """Get total number of messages in history."""
        state = self.get_conversation_state(user_id)
        return len(state.messages)


# Global instance for convenience
_conversation_store: Optional[ConversationStore] = None


def get_conversation_store() -> ConversationStore:
    """Get or create the global ConversationStore instance."""
    global _conversation_store
    if _conversation_store is None:
        _conversation_store = ConversationStore()
    return _conversation_store


def init_conversation_store() -> ConversationStore:
    """Initialize and return the conversation store."""
    return get_conversation_store()
