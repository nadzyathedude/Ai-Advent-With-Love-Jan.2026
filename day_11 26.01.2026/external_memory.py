"""
External Memory Module

Provides persistent storage for conversation history with archiving support.
Supports both SQLite and JSON storage backends.

Key features:
- Messages are NEVER deleted, only marked as inactive (archived)
- Multi-level summarization with compression
- Per-user isolation
- Chunk-based message grouping for summarization
"""

import json
import logging
import os
import sqlite3
import tempfile
import shutil
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Iterator

logger = logging.getLogger(__name__)

# Default paths
DEFAULT_SQLITE_PATH = Path(__file__).parent / "memory.db"
DEFAULT_JSON_PATH = Path(__file__).parent / "memory.json"


@dataclass
class Message:
    """Represents a single message in conversation."""
    id: int
    user_id: int
    role: str  # "user", "assistant", or "system"
    content: str
    created_at: datetime
    is_active: bool = True
    chunk_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
            "is_active": self.is_active,
            "chunk_id": self.chunk_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            role=data["role"],
            content=data["content"],
            created_at=datetime.fromisoformat(data["created_at"]) if isinstance(data["created_at"], str) else data["created_at"],
            is_active=data.get("is_active", True),
            chunk_id=data.get("chunk_id")
        )


@dataclass
class Summary:
    """Represents a summary of archived messages."""
    id: int
    user_id: int
    summary_text: str
    created_at: datetime
    level: int = 1  # Compression level (1 = first level, 2+ = meta-summaries)
    source_chunk_ids: List[int] = field(default_factory=list)
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "summary_text": self.summary_text,
            "created_at": self.created_at.isoformat(),
            "level": self.level,
            "source_chunk_ids": self.source_chunk_ids,
            "is_active": self.is_active
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Summary":
        return cls(
            id=data["id"],
            user_id=data["user_id"],
            summary_text=data["summary_text"],
            created_at=datetime.fromisoformat(data["created_at"]) if isinstance(data["created_at"], str) else data["created_at"],
            level=data.get("level", 1),
            source_chunk_ids=data.get("source_chunk_ids", []),
            is_active=data.get("is_active", True)
        )


@dataclass
class UserConfig:
    """User's external memory configuration."""
    user_id: int
    storage_type: str  # "sqlite" or "json"
    summary_every_n: int  # Messages before summarization
    memory_enabled: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "storage_type": self.storage_type,
            "summary_every_n": self.summary_every_n,
            "memory_enabled": self.memory_enabled,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserConfig":
        return cls(
            user_id=data["user_id"],
            storage_type=data.get("storage_type", "sqlite"),
            summary_every_n=data.get("summary_every_n", 10),
            memory_enabled=data.get("memory_enabled", False),
            created_at=datetime.fromisoformat(data["created_at"]) if isinstance(data.get("created_at"), str) else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if isinstance(data.get("updated_at"), str) else datetime.now()
        )


class ExternalMemoryBackend(ABC):
    """Abstract base class for external memory storage backends."""

    @abstractmethod
    def init_storage(self) -> None:
        """Initialize storage (create tables/files)."""
        pass

    @abstractmethod
    def get_user_config(self, user_id: int) -> Optional[UserConfig]:
        """Get user configuration."""
        pass

    @abstractmethod
    def set_user_config(self, config: UserConfig) -> None:
        """Save user configuration."""
        pass

    @abstractmethod
    def add_message(self, user_id: int, role: str, content: str) -> Message:
        """Add a new message."""
        pass

    @abstractmethod
    def get_active_messages(self, user_id: int, limit: Optional[int] = None) -> List[Message]:
        """Get active (non-archived) messages."""
        pass

    @abstractmethod
    def get_messages_since_last_summary(self, user_id: int) -> List[Message]:
        """Get messages that haven't been summarized yet."""
        pass

    @abstractmethod
    def archive_messages(self, message_ids: List[int], chunk_id: int) -> None:
        """Mark messages as archived (is_active=False) and assign chunk_id."""
        pass

    @abstractmethod
    def add_summary(self, user_id: int, summary_text: str, level: int,
                    source_chunk_ids: List[int]) -> Summary:
        """Add a new summary."""
        pass

    @abstractmethod
    def get_active_summaries(self, user_id: int, max_level: Optional[int] = None) -> List[Summary]:
        """Get active summaries."""
        pass

    @abstractmethod
    def archive_summaries(self, summary_ids: List[int]) -> None:
        """Mark summaries as archived."""
        pass

    @abstractmethod
    def search_messages(self, user_id: int, query: str,
                        include_inactive: bool = True,
                        limit: int = 10) -> List[Message]:
        """Search messages by content."""
        pass

    @abstractmethod
    def get_next_chunk_id(self, user_id: int) -> int:
        """Get the next available chunk ID for a user."""
        pass

    @abstractmethod
    def get_message_count_since_last_summary(self, user_id: int) -> int:
        """Count messages since last summarization (user turns only)."""
        pass

    @abstractmethod
    def get_all_messages(self, user_id: int, include_inactive: bool = True) -> List[Message]:
        """Get all messages for a user."""
        pass

    @abstractmethod
    def get_statistics(self, user_id: int) -> Dict[str, Any]:
        """Get memory statistics for a user."""
        pass


class SQLiteBackend(ExternalMemoryBackend):
    """SQLite implementation of external memory storage."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_SQLITE_PATH
        self.init_storage()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_storage(self) -> None:
        """Create database tables if they don't exist."""
        with self._get_connection() as conn:
            # Users table for configuration
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    storage_type TEXT NOT NULL DEFAULT 'sqlite',
                    summary_every_n INTEGER NOT NULL DEFAULT 10,
                    memory_enabled INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Messages table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    chunk_id INTEGER,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            # Create indexes for messages
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_user_id
                ON messages(user_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_user_active
                ON messages(user_id, is_active)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_chunk
                ON messages(chunk_id)
            """)

            # Summaries table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    summary_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    level INTEGER NOT NULL DEFAULT 1,
                    source_chunk_ids TEXT NOT NULL DEFAULT '[]',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            # Create indexes for summaries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_summaries_user_id
                ON summaries(user_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_summaries_user_active
                ON summaries(user_id, is_active)
            """)

            conn.commit()
        logger.info(f"SQLite storage initialized at {self.db_path}")

    def get_user_config(self, user_id: int) -> Optional[UserConfig]:
        """Get user configuration."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return UserConfig(
            user_id=row["user_id"],
            storage_type=row["storage_type"],
            summary_every_n=row["summary_every_n"],
            memory_enabled=row["memory_enabled"] == 1,
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.now()
        )

    def set_user_config(self, config: UserConfig) -> None:
        """Save user configuration."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO users (user_id, storage_type, summary_every_n, memory_enabled, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    storage_type = excluded.storage_type,
                    summary_every_n = excluded.summary_every_n,
                    memory_enabled = excluded.memory_enabled,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                config.user_id,
                config.storage_type,
                config.summary_every_n,
                1 if config.memory_enabled else 0
            ))
            conn.commit()
        logger.debug(f"User {config.user_id} config saved: {config}")

    def add_message(self, user_id: int, role: str, content: str) -> Message:
        """Add a new message."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO messages (user_id, role, content, created_at, is_active)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1)
            """, (user_id, role, content))
            message_id = cursor.lastrowid

            cursor = conn.execute(
                "SELECT created_at FROM messages WHERE id = ?",
                (message_id,)
            )
            row = cursor.fetchone()
            conn.commit()

        return Message(
            id=message_id,
            user_id=user_id,
            role=role,
            content=content,
            created_at=datetime.fromisoformat(row["created_at"]),
            is_active=True,
            chunk_id=None
        )

    def get_active_messages(self, user_id: int, limit: Optional[int] = None) -> List[Message]:
        """Get active (non-archived) messages."""
        query = """
            SELECT * FROM messages
            WHERE user_id = ? AND is_active = 1
            ORDER BY created_at ASC
        """
        if limit:
            query += f" LIMIT {limit}"

        with self._get_connection() as conn:
            cursor = conn.execute(query, (user_id,))
            rows = cursor.fetchall()

        return [self._row_to_message(row) for row in rows]

    def get_messages_since_last_summary(self, user_id: int) -> List[Message]:
        """Get active messages that haven't been assigned to a chunk yet."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM messages
                WHERE user_id = ? AND is_active = 1 AND chunk_id IS NULL
                ORDER BY created_at ASC
            """, (user_id,))
            rows = cursor.fetchall()

        return [self._row_to_message(row) for row in rows]

    def archive_messages(self, message_ids: List[int], chunk_id: int) -> None:
        """Mark messages as archived and assign chunk_id."""
        if not message_ids:
            return

        with self._get_connection() as conn:
            placeholders = ",".join("?" * len(message_ids))
            conn.execute(f"""
                UPDATE messages
                SET is_active = 0, chunk_id = ?
                WHERE id IN ({placeholders})
            """, [chunk_id] + message_ids)
            conn.commit()
        logger.debug(f"Archived {len(message_ids)} messages to chunk {chunk_id}")

    def add_summary(self, user_id: int, summary_text: str, level: int,
                    source_chunk_ids: List[int]) -> Summary:
        """Add a new summary."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO summaries (user_id, summary_text, level, source_chunk_ids, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (user_id, summary_text, level, json.dumps(source_chunk_ids)))
            summary_id = cursor.lastrowid

            cursor = conn.execute(
                "SELECT created_at FROM summaries WHERE id = ?",
                (summary_id,)
            )
            row = cursor.fetchone()
            conn.commit()

        return Summary(
            id=summary_id,
            user_id=user_id,
            summary_text=summary_text,
            created_at=datetime.fromisoformat(row["created_at"]),
            level=level,
            source_chunk_ids=source_chunk_ids,
            is_active=True
        )

    def get_active_summaries(self, user_id: int, max_level: Optional[int] = None) -> List[Summary]:
        """Get active summaries, optionally filtered by max level."""
        if max_level is not None:
            query = """
                SELECT * FROM summaries
                WHERE user_id = ? AND is_active = 1 AND level <= ?
                ORDER BY level DESC, created_at DESC
            """
            params = (user_id, max_level)
        else:
            query = """
                SELECT * FROM summaries
                WHERE user_id = ? AND is_active = 1
                ORDER BY level DESC, created_at DESC
            """
            params = (user_id,)

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        return [self._row_to_summary(row) for row in rows]

    def archive_summaries(self, summary_ids: List[int]) -> None:
        """Mark summaries as archived."""
        if not summary_ids:
            return

        with self._get_connection() as conn:
            placeholders = ",".join("?" * len(summary_ids))
            conn.execute(f"""
                UPDATE summaries SET is_active = 0
                WHERE id IN ({placeholders})
            """, summary_ids)
            conn.commit()
        logger.debug(f"Archived {len(summary_ids)} summaries")

    def search_messages(self, user_id: int, query: str,
                        include_inactive: bool = True,
                        limit: int = 10) -> List[Message]:
        """Search messages by content using LIKE."""
        search_query = f"%{query}%"

        if include_inactive:
            sql = """
                SELECT * FROM messages
                WHERE user_id = ? AND content LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
            """
        else:
            sql = """
                SELECT * FROM messages
                WHERE user_id = ? AND content LIKE ? AND is_active = 1
                ORDER BY created_at DESC
                LIMIT ?
            """

        with self._get_connection() as conn:
            cursor = conn.execute(sql, (user_id, search_query, limit))
            rows = cursor.fetchall()

        return [self._row_to_message(row) for row in rows]

    def get_next_chunk_id(self, user_id: int) -> int:
        """Get the next available chunk ID."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT COALESCE(MAX(chunk_id), 0) + 1 as next_chunk
                FROM messages WHERE user_id = ?
            """, (user_id,))
            row = cursor.fetchone()
        return row["next_chunk"]

    def get_message_count_since_last_summary(self, user_id: int) -> int:
        """Count user messages since last summarization (active, no chunk_id)."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) as count FROM messages
                WHERE user_id = ? AND is_active = 1 AND chunk_id IS NULL AND role = 'user'
            """, (user_id,))
            row = cursor.fetchone()
        return row["count"]

    def get_all_messages(self, user_id: int, include_inactive: bool = True) -> List[Message]:
        """Get all messages for a user."""
        if include_inactive:
            query = "SELECT * FROM messages WHERE user_id = ? ORDER BY created_at ASC"
        else:
            query = "SELECT * FROM messages WHERE user_id = ? AND is_active = 1 ORDER BY created_at ASC"

        with self._get_connection() as conn:
            cursor = conn.execute(query, (user_id,))
            rows = cursor.fetchall()

        return [self._row_to_message(row) for row in rows]

    def get_statistics(self, user_id: int) -> Dict[str, Any]:
        """Get memory statistics for a user."""
        with self._get_connection() as conn:
            # Total messages
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM messages WHERE user_id = ?",
                (user_id,)
            )
            total_messages = cursor.fetchone()["count"]

            # Active messages
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM messages WHERE user_id = ? AND is_active = 1",
                (user_id,)
            )
            active_messages = cursor.fetchone()["count"]

            # Archived messages
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM messages WHERE user_id = ? AND is_active = 0",
                (user_id,)
            )
            archived_messages = cursor.fetchone()["count"]

            # Number of chunks
            cursor = conn.execute(
                "SELECT COUNT(DISTINCT chunk_id) as count FROM messages WHERE user_id = ? AND chunk_id IS NOT NULL",
                (user_id,)
            )
            num_chunks = cursor.fetchone()["count"]

            # Total summaries
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM summaries WHERE user_id = ?",
                (user_id,)
            )
            total_summaries = cursor.fetchone()["count"]

            # Active summaries
            cursor = conn.execute(
                "SELECT COUNT(*) as count FROM summaries WHERE user_id = ? AND is_active = 1",
                (user_id,)
            )
            active_summaries = cursor.fetchone()["count"]

            # Max summary level
            cursor = conn.execute(
                "SELECT COALESCE(MAX(level), 0) as max_level FROM summaries WHERE user_id = ? AND is_active = 1",
                (user_id,)
            )
            max_level = cursor.fetchone()["max_level"]

            # Messages since last summary
            messages_since_summary = self.get_message_count_since_last_summary(user_id)

        return {
            "total_messages": total_messages,
            "active_messages": active_messages,
            "archived_messages": archived_messages,
            "num_chunks": num_chunks,
            "total_summaries": total_summaries,
            "active_summaries": active_summaries,
            "max_summary_level": max_level,
            "messages_since_last_summary": messages_since_summary
        }

    def _row_to_message(self, row: sqlite3.Row) -> Message:
        """Convert database row to Message object."""
        return Message(
            id=row["id"],
            user_id=row["user_id"],
            role=row["role"],
            content=row["content"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
            is_active=row["is_active"] == 1,
            chunk_id=row["chunk_id"]
        )

    def _row_to_summary(self, row: sqlite3.Row) -> Summary:
        """Convert database row to Summary object."""
        return Summary(
            id=row["id"],
            user_id=row["user_id"],
            summary_text=row["summary_text"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
            level=row["level"],
            source_chunk_ids=json.loads(row["source_chunk_ids"]),
            is_active=row["is_active"] == 1
        )


class JSONBackend(ExternalMemoryBackend):
    """JSON file implementation of external memory storage."""

    def __init__(self, json_path: Optional[Path] = None):
        self.json_path = json_path or DEFAULT_JSON_PATH
        self._data: Dict[str, Any] = {}
        self._next_message_id = 1
        self._next_summary_id = 1
        self.init_storage()

    def init_storage(self) -> None:
        """Initialize JSON storage file."""
        if self.json_path.exists():
            try:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                # Update ID counters
                self._update_id_counters()
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error loading JSON storage: {e}")
                self._data = {"users": {}, "messages": {}, "summaries": {}}
        else:
            self._data = {"users": {}, "messages": {}, "summaries": {}}
            self._save()
        logger.info(f"JSON storage initialized at {self.json_path}")

    def _update_id_counters(self) -> None:
        """Update ID counters based on existing data."""
        max_msg_id = 0
        max_sum_id = 0

        for user_msgs in self._data.get("messages", {}).values():
            for msg in user_msgs:
                if msg.get("id", 0) > max_msg_id:
                    max_msg_id = msg["id"]

        for user_sums in self._data.get("summaries", {}).values():
            for summ in user_sums:
                if summ.get("id", 0) > max_sum_id:
                    max_sum_id = summ["id"]

        self._next_message_id = max_msg_id + 1
        self._next_summary_id = max_sum_id + 1

    def _save(self) -> None:
        """Atomically save data to JSON file."""
        # Write to temp file, then rename for atomicity
        temp_fd, temp_path = tempfile.mkstemp(
            dir=self.json_path.parent,
            prefix=".memory_",
            suffix=".json.tmp"
        )
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            shutil.move(temp_path, self.json_path)
        except Exception as e:
            logger.error(f"Error saving JSON storage: {e}")
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def _get_user_key(self, user_id: int) -> str:
        """Get string key for user in JSON data."""
        return str(user_id)

    def get_user_config(self, user_id: int) -> Optional[UserConfig]:
        """Get user configuration."""
        user_key = self._get_user_key(user_id)
        user_data = self._data.get("users", {}).get(user_key)

        if user_data is None:
            return None

        return UserConfig.from_dict(user_data)

    def set_user_config(self, config: UserConfig) -> None:
        """Save user configuration."""
        user_key = self._get_user_key(config.user_id)

        if "users" not in self._data:
            self._data["users"] = {}

        config.updated_at = datetime.now()
        self._data["users"][user_key] = config.to_dict()
        self._save()
        logger.debug(f"User {config.user_id} config saved")

    def add_message(self, user_id: int, role: str, content: str) -> Message:
        """Add a new message."""
        user_key = self._get_user_key(user_id)

        if "messages" not in self._data:
            self._data["messages"] = {}
        if user_key not in self._data["messages"]:
            self._data["messages"][user_key] = []

        message = Message(
            id=self._next_message_id,
            user_id=user_id,
            role=role,
            content=content,
            created_at=datetime.now(),
            is_active=True,
            chunk_id=None
        )
        self._next_message_id += 1

        self._data["messages"][user_key].append(message.to_dict())
        self._save()
        return message

    def get_active_messages(self, user_id: int, limit: Optional[int] = None) -> List[Message]:
        """Get active (non-archived) messages."""
        user_key = self._get_user_key(user_id)
        messages_data = self._data.get("messages", {}).get(user_key, [])

        active_messages = [
            Message.from_dict(m) for m in messages_data
            if m.get("is_active", True)
        ]

        # Sort by created_at
        active_messages.sort(key=lambda m: m.created_at)

        if limit:
            active_messages = active_messages[:limit]

        return active_messages

    def get_messages_since_last_summary(self, user_id: int) -> List[Message]:
        """Get active messages without chunk_id."""
        user_key = self._get_user_key(user_id)
        messages_data = self._data.get("messages", {}).get(user_key, [])

        messages = [
            Message.from_dict(m) for m in messages_data
            if m.get("is_active", True) and m.get("chunk_id") is None
        ]

        messages.sort(key=lambda m: m.created_at)
        return messages

    def archive_messages(self, message_ids: List[int], chunk_id: int) -> None:
        """Mark messages as archived and assign chunk_id."""
        if not message_ids:
            return

        message_id_set = set(message_ids)

        for user_key, messages in self._data.get("messages", {}).items():
            for msg in messages:
                if msg["id"] in message_id_set:
                    msg["is_active"] = False
                    msg["chunk_id"] = chunk_id

        self._save()
        logger.debug(f"Archived {len(message_ids)} messages to chunk {chunk_id}")

    def add_summary(self, user_id: int, summary_text: str, level: int,
                    source_chunk_ids: List[int]) -> Summary:
        """Add a new summary."""
        user_key = self._get_user_key(user_id)

        if "summaries" not in self._data:
            self._data["summaries"] = {}
        if user_key not in self._data["summaries"]:
            self._data["summaries"][user_key] = []

        summary = Summary(
            id=self._next_summary_id,
            user_id=user_id,
            summary_text=summary_text,
            created_at=datetime.now(),
            level=level,
            source_chunk_ids=source_chunk_ids,
            is_active=True
        )
        self._next_summary_id += 1

        self._data["summaries"][user_key].append(summary.to_dict())
        self._save()
        return summary

    def get_active_summaries(self, user_id: int, max_level: Optional[int] = None) -> List[Summary]:
        """Get active summaries."""
        user_key = self._get_user_key(user_id)
        summaries_data = self._data.get("summaries", {}).get(user_key, [])

        summaries = [
            Summary.from_dict(s) for s in summaries_data
            if s.get("is_active", True) and
               (max_level is None or s.get("level", 1) <= max_level)
        ]

        # Sort by level descending, then by created_at descending
        summaries.sort(key=lambda s: (-s.level, s.created_at), reverse=False)
        summaries.sort(key=lambda s: s.level, reverse=True)

        return summaries

    def archive_summaries(self, summary_ids: List[int]) -> None:
        """Mark summaries as archived."""
        if not summary_ids:
            return

        summary_id_set = set(summary_ids)

        for user_key, summaries in self._data.get("summaries", {}).items():
            for summ in summaries:
                if summ["id"] in summary_id_set:
                    summ["is_active"] = False

        self._save()
        logger.debug(f"Archived {len(summary_ids)} summaries")

    def search_messages(self, user_id: int, query: str,
                        include_inactive: bool = True,
                        limit: int = 10) -> List[Message]:
        """Search messages by content."""
        user_key = self._get_user_key(user_id)
        messages_data = self._data.get("messages", {}).get(user_key, [])

        query_lower = query.lower()
        matching = []

        for msg_data in messages_data:
            if not include_inactive and not msg_data.get("is_active", True):
                continue
            if query_lower in msg_data.get("content", "").lower():
                matching.append(Message.from_dict(msg_data))

        # Sort by created_at descending (most recent first)
        matching.sort(key=lambda m: m.created_at, reverse=True)

        return matching[:limit]

    def get_next_chunk_id(self, user_id: int) -> int:
        """Get the next available chunk ID."""
        user_key = self._get_user_key(user_id)
        messages_data = self._data.get("messages", {}).get(user_key, [])

        max_chunk = 0
        for msg in messages_data:
            chunk_id = msg.get("chunk_id")
            if chunk_id is not None and chunk_id > max_chunk:
                max_chunk = chunk_id

        return max_chunk + 1

    def get_message_count_since_last_summary(self, user_id: int) -> int:
        """Count user messages since last summarization."""
        messages = self.get_messages_since_last_summary(user_id)
        return sum(1 for m in messages if m.role == "user")

    def get_all_messages(self, user_id: int, include_inactive: bool = True) -> List[Message]:
        """Get all messages for a user."""
        user_key = self._get_user_key(user_id)
        messages_data = self._data.get("messages", {}).get(user_key, [])

        messages = []
        for msg_data in messages_data:
            if include_inactive or msg_data.get("is_active", True):
                messages.append(Message.from_dict(msg_data))

        messages.sort(key=lambda m: m.created_at)
        return messages

    def get_statistics(self, user_id: int) -> Dict[str, Any]:
        """Get memory statistics for a user."""
        user_key = self._get_user_key(user_id)

        messages_data = self._data.get("messages", {}).get(user_key, [])
        summaries_data = self._data.get("summaries", {}).get(user_key, [])

        total_messages = len(messages_data)
        active_messages = sum(1 for m in messages_data if m.get("is_active", True))
        archived_messages = total_messages - active_messages

        chunk_ids = set()
        for msg in messages_data:
            if msg.get("chunk_id") is not None:
                chunk_ids.add(msg["chunk_id"])

        total_summaries = len(summaries_data)
        active_summaries = sum(1 for s in summaries_data if s.get("is_active", True))

        max_level = 0
        for summ in summaries_data:
            if summ.get("is_active", True):
                level = summ.get("level", 1)
                if level > max_level:
                    max_level = level

        messages_since_summary = self.get_message_count_since_last_summary(user_id)

        return {
            "total_messages": total_messages,
            "active_messages": active_messages,
            "archived_messages": archived_messages,
            "num_chunks": len(chunk_ids),
            "total_summaries": total_summaries,
            "active_summaries": active_summaries,
            "max_summary_level": max_level,
            "messages_since_last_summary": messages_since_summary
        }


class ExternalMemory:
    """
    Main external memory interface.

    Provides a unified interface for both SQLite and JSON backends.
    Handles storage type selection per user and delegates to appropriate backend.
    """

    def __init__(
        self,
        sqlite_path: Optional[Path] = None,
        json_path: Optional[Path] = None
    ):
        self.sqlite_backend = SQLiteBackend(sqlite_path)
        self.json_backend = JSONBackend(json_path)
        self._default_storage = "sqlite"

    def get_backend(self, user_id: int) -> ExternalMemoryBackend:
        """Get the appropriate backend for a user."""
        # Check SQLite first for user config
        config = self.sqlite_backend.get_user_config(user_id)
        if config is not None:
            if config.storage_type == "json":
                return self.json_backend
            return self.sqlite_backend

        # Check JSON backend
        config = self.json_backend.get_user_config(user_id)
        if config is not None:
            if config.storage_type == "json":
                return self.json_backend
            return self.sqlite_backend

        # Default to SQLite
        return self.sqlite_backend

    def get_backend_by_type(self, storage_type: str) -> ExternalMemoryBackend:
        """Get backend by storage type."""
        if storage_type == "json":
            return self.json_backend
        return self.sqlite_backend

    def get_user_config(self, user_id: int) -> Optional[UserConfig]:
        """Get user configuration (checks both backends)."""
        # Try SQLite first
        config = self.sqlite_backend.get_user_config(user_id)
        if config:
            return config

        # Try JSON
        config = self.json_backend.get_user_config(user_id)
        return config

    def set_user_config(self, config: UserConfig) -> None:
        """Save user configuration to the appropriate backend."""
        backend = self.get_backend_by_type(config.storage_type)
        backend.set_user_config(config)

    def is_enabled(self, user_id: int) -> bool:
        """Check if external memory is enabled for user."""
        config = self.get_user_config(user_id)
        return config is not None and config.memory_enabled

    def add_message(self, user_id: int, role: str, content: str) -> Message:
        """Add a message to user's external memory."""
        backend = self.get_backend(user_id)
        return backend.add_message(user_id, role, content)

    def get_active_messages(self, user_id: int, limit: Optional[int] = None) -> List[Message]:
        """Get active messages."""
        backend = self.get_backend(user_id)
        return backend.get_active_messages(user_id, limit)

    def get_messages_since_last_summary(self, user_id: int) -> List[Message]:
        """Get messages that need summarization."""
        backend = self.get_backend(user_id)
        return backend.get_messages_since_last_summary(user_id)

    def archive_messages(self, user_id: int, message_ids: List[int], chunk_id: int) -> None:
        """Archive messages."""
        backend = self.get_backend(user_id)
        backend.archive_messages(message_ids, chunk_id)

    def add_summary(self, user_id: int, summary_text: str, level: int,
                    source_chunk_ids: List[int]) -> Summary:
        """Add a summary."""
        backend = self.get_backend(user_id)
        return backend.add_summary(user_id, summary_text, level, source_chunk_ids)

    def get_active_summaries(self, user_id: int, max_level: Optional[int] = None) -> List[Summary]:
        """Get active summaries."""
        backend = self.get_backend(user_id)
        return backend.get_active_summaries(user_id, max_level)

    def archive_summaries(self, user_id: int, summary_ids: List[int]) -> None:
        """Archive summaries."""
        backend = self.get_backend(user_id)
        backend.archive_summaries(summary_ids)

    def search_messages(self, user_id: int, query: str,
                        include_inactive: bool = True,
                        limit: int = 10) -> List[Message]:
        """Search messages."""
        backend = self.get_backend(user_id)
        return backend.search_messages(user_id, query, include_inactive, limit)

    def get_next_chunk_id(self, user_id: int) -> int:
        """Get next chunk ID."""
        backend = self.get_backend(user_id)
        return backend.get_next_chunk_id(user_id)

    def get_message_count_since_last_summary(self, user_id: int) -> int:
        """Get message count since last summary."""
        backend = self.get_backend(user_id)
        return backend.get_message_count_since_last_summary(user_id)

    def should_summarize(self, user_id: int) -> bool:
        """Check if summarization should be triggered."""
        config = self.get_user_config(user_id)
        if config is None or not config.memory_enabled:
            return False

        count = self.get_message_count_since_last_summary(user_id)
        return count >= config.summary_every_n

    def get_statistics(self, user_id: int) -> Dict[str, Any]:
        """Get memory statistics."""
        backend = self.get_backend(user_id)
        stats = backend.get_statistics(user_id)

        config = self.get_user_config(user_id)
        if config:
            stats["storage_type"] = config.storage_type
            stats["summary_every_n"] = config.summary_every_n
            stats["memory_enabled"] = config.memory_enabled
        else:
            stats["storage_type"] = None
            stats["summary_every_n"] = None
            stats["memory_enabled"] = False

        return stats


# Global instance
_external_memory: Optional[ExternalMemory] = None


def get_external_memory() -> ExternalMemory:
    """Get or create the global ExternalMemory instance."""
    global _external_memory
    if _external_memory is None:
        _external_memory = ExternalMemory()
    return _external_memory


def init_external_memory(
    sqlite_path: Optional[Path] = None,
    json_path: Optional[Path] = None
) -> ExternalMemory:
    """Initialize and return the external memory."""
    global _external_memory
    _external_memory = ExternalMemory(sqlite_path, json_path)
    return _external_memory
