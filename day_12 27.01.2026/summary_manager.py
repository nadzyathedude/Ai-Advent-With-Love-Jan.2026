"""
Summary Manager Module

Handles dialogue summarization using OpenAI with multi-level compression.
Decides when to summarize, generates summaries, and manages the archival process.

Key features:
- Multi-level summarization (level 1 for messages, level 2+ for meta-summaries)
- Archives messages without deleting them
- Integrates with both old ConversationStore and new ExternalMemory
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from openai import OpenAI

from conversation_store import ConversationStore, ConversationState, get_conversation_store
from external_memory import (
    ExternalMemory,
    Message,
    Summary,
    UserConfig,
    get_external_memory
)

logger = logging.getLogger(__name__)

# Model used for summarization (cheaper model for cost efficiency)
SUMMARIZATION_MODEL = "gpt-4o-mini"

# Summarization prompt template for messages
SUMMARIZATION_PROMPT = """You are a conversation summarizer. Your task is to create a concise but comprehensive summary of the conversation below.

The summary MUST preserve:
1. User's goals and preferences expressed in the conversation
2. Key decisions made and instructions given
3. Important facts mentioned (names, dates, numbers, specific details)
4. Unresolved questions or pending next steps
5. The overall context needed to continue the conversation naturally

Guidelines:
- Write in second person ("You discussed...", "You asked about...")
- Be concise but don't lose important context
- Focus on information that would be needed to continue the conversation
- Keep the summary to 200-400 words maximum
- Use bullet points for key items when appropriate

Conversation to summarize:
"""

# Meta-summarization prompt for compressing summaries
META_SUMMARIZATION_PROMPT = """You are summarizing multiple conversation summaries into a single, higher-level summary.

Your task is to:
1. Combine the key information from all summaries
2. Preserve the most important facts, decisions, and context
3. Remove redundancy while keeping critical details
4. Create a coherent narrative that captures the full conversation history

Guidelines:
- Write in second person ("You discussed...", "You asked about...")
- Be concise but comprehensive
- Prioritize long-term relevant information over transient details
- Keep the meta-summary to 300-500 words maximum

Previous summaries to combine:
"""

# Number of recent messages to retain for continuity after summarization (legacy)
MESSAGES_TO_RETAIN = 2

# Thresholds for multi-level compression
MAX_ACTIVE_LEVEL1_SUMMARIES = 5  # Trigger level-2 when exceeding this
MAX_ACTIVE_SUMMARIES_TOTAL = 10  # Maximum total active summaries
SUMMARY_TOKEN_THRESHOLD = 3000  # Trigger compression when summaries exceed this


class SummaryManager:
    """
    Manages the summarization process for conversations.

    Works with both legacy ConversationStore and new ExternalMemory.
    Supports multi-level summarization with archival (never deletes).
    """

    def __init__(
        self,
        openai_client: OpenAI,
        conversation_store: Optional[ConversationStore] = None,
        external_memory: Optional[ExternalMemory] = None,
        summarization_model: str = SUMMARIZATION_MODEL,
        messages_to_retain: int = MESSAGES_TO_RETAIN
    ):
        """
        Initialize SummaryManager.

        Args:
            openai_client: OpenAI client instance
            conversation_store: ConversationStore instance (legacy support)
            external_memory: ExternalMemory instance (new system)
            summarization_model: Model to use for summarization
            messages_to_retain: Number of recent turns to keep (legacy)
        """
        self.client = openai_client
        self.store = conversation_store or get_conversation_store()
        self.memory = external_memory or get_external_memory()
        self.summarization_model = summarization_model
        self.messages_to_retain = messages_to_retain

    def _use_external_memory(self, user_id: int) -> bool:
        """Check if user should use external memory."""
        config = self.memory.get_user_config(user_id)
        return config is not None and config.memory_enabled

    def should_summarize(self, user_id: int) -> bool:
        """
        Check if summarization should be triggered for user.

        Args:
            user_id: Telegram user ID

        Returns:
            True if summarization should occur
        """
        if self._use_external_memory(user_id):
            return self.memory.should_summarize(user_id)
        else:
            return self.store.should_summarize(user_id)

    def format_messages_for_summary(self, messages: List[Dict[str, str]]) -> str:
        """
        Format conversation messages for the summarization prompt.

        Args:
            messages: List of message dicts with 'role' and 'content'

        Returns:
            Formatted string representation of the conversation
        """
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    def format_external_messages_for_summary(self, messages: List[Message]) -> str:
        """
        Format Message objects for the summarization prompt.

        Args:
            messages: List of Message objects

        Returns:
            Formatted string representation of the conversation
        """
        lines = []
        for msg in messages:
            role = msg.role.upper()
            lines.append(f"{role}: {msg.content}")
        return "\n\n".join(lines)

    def format_summaries_for_meta_summary(self, summaries: List[Summary]) -> str:
        """
        Format summaries for meta-summarization.

        Args:
            summaries: List of Summary objects

        Returns:
            Formatted string of summaries
        """
        parts = []
        for i, summary in enumerate(summaries, 1):
            parts.append(f"--- Summary {i} (Level {summary.level}) ---")
            parts.append(summary.summary_text)
        return "\n\n".join(parts)

    async def generate_summary(
        self,
        messages: List[Dict[str, str]]
    ) -> Optional[str]:
        """
        Generate a summary of the given messages using OpenAI.

        Args:
            messages: List of messages to summarize

        Returns:
            Summary text or None if generation failed
        """
        if not messages:
            logger.warning("No messages to summarize")
            return None

        try:
            formatted_conversation = self.format_messages_for_summary(messages)
            prompt = SUMMARIZATION_PROMPT + formatted_conversation

            response = self.client.chat.completions.create(
                model=self.summarization_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that creates conversation summaries."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800,
                temperature=0.3
            )

            summary = response.choices[0].message.content
            logger.info(
                f"Summary generated: {len(messages)} messages -> "
                f"{len(summary)} chars, model={self.summarization_model}"
            )
            return summary

        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            return None

    async def generate_summary_from_external(
        self,
        messages: List[Message]
    ) -> Optional[str]:
        """
        Generate a summary from Message objects.

        Args:
            messages: List of Message objects

        Returns:
            Summary text or None if generation failed
        """
        if not messages:
            logger.warning("No messages to summarize")
            return None

        try:
            formatted_conversation = self.format_external_messages_for_summary(messages)
            prompt = SUMMARIZATION_PROMPT + formatted_conversation

            response = self.client.chat.completions.create(
                model=self.summarization_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that creates conversation summaries."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800,
                temperature=0.3
            )

            summary = response.choices[0].message.content
            logger.info(
                f"Summary generated: {len(messages)} messages -> "
                f"{len(summary)} chars"
            )
            return summary

        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            return None

    async def generate_meta_summary(
        self,
        summaries: List[Summary]
    ) -> Optional[str]:
        """
        Generate a meta-summary from multiple summaries.

        Args:
            summaries: List of Summary objects to combine

        Returns:
            Meta-summary text or None if generation failed
        """
        if not summaries:
            logger.warning("No summaries to meta-summarize")
            return None

        try:
            formatted_summaries = self.format_summaries_for_meta_summary(summaries)
            prompt = META_SUMMARIZATION_PROMPT + formatted_summaries

            response = self.client.chat.completions.create(
                model=self.summarization_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that combines conversation summaries."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000,
                temperature=0.3
            )

            meta_summary = response.choices[0].message.content
            logger.info(
                f"Meta-summary generated: {len(summaries)} summaries -> "
                f"{len(meta_summary)} chars"
            )
            return meta_summary

        except Exception as e:
            logger.error(f"Failed to generate meta-summary: {e}")
            return None

    async def summarize_if_needed(self, user_id: int) -> bool:
        """
        Check and perform summarization if threshold is reached.

        This should be called after completing an assistant response.

        Args:
            user_id: Telegram user ID

        Returns:
            True if summarization was performed, False otherwise
        """
        if not self.should_summarize(user_id):
            return False

        return await self.force_summarize(user_id)

    async def force_summarize(self, user_id: int) -> bool:
        """
        Force summarization regardless of threshold.

        Args:
            user_id: Telegram user ID

        Returns:
            True if summarization was successful, False otherwise
        """
        if self._use_external_memory(user_id):
            return await self._force_summarize_external(user_id)
        else:
            return await self._force_summarize_legacy(user_id)

    async def _force_summarize_legacy(self, user_id: int) -> bool:
        """Legacy summarization using ConversationStore."""
        messages = self.store.get_messages_for_summarization(user_id)

        if not messages:
            logger.warning(f"No messages to summarize for user {user_id}")
            return False

        logger.info(
            f"Summarization triggered for user {user_id}: "
            f"{len(messages)} messages at {datetime.now().isoformat()}"
        )

        summary = await self.generate_summary(messages)

        if summary is None:
            logger.error(
                f"Summarization failed for user {user_id}, "
                "keeping original history"
            )
            return False

        self.store.apply_summary(
            user_id=user_id,
            summary=summary,
            keep_last_n_messages=self.messages_to_retain
        )

        logger.info(
            f"Summarization completed for user {user_id}: "
            f"retained {self.messages_to_retain} message pairs"
        )
        return True

    async def _force_summarize_external(self, user_id: int) -> bool:
        """
        Summarization using ExternalMemory with archival.

        Key difference: messages are archived (is_active=0), not deleted.
        """
        messages = self.memory.get_messages_since_last_summary(user_id)

        if not messages:
            logger.warning(f"No messages to summarize for user {user_id}")
            return False

        logger.info(
            f"External memory summarization triggered for user {user_id}: "
            f"{len(messages)} messages"
        )

        # Generate summary
        summary_text = await self.generate_summary_from_external(messages)

        if summary_text is None:
            logger.error(
                f"Summarization failed for user {user_id}, "
                "keeping messages active"
            )
            return False

        # Get next chunk ID and archive messages
        chunk_id = self.memory.get_next_chunk_id(user_id)
        message_ids = [msg.id for msg in messages]

        # Archive messages (mark as inactive, assign chunk_id)
        # IMPORTANT: We do NOT delete messages, only mark them
        self.memory.archive_messages(user_id, message_ids, chunk_id)

        # Add level-1 summary
        self.memory.add_summary(
            user_id=user_id,
            summary_text=summary_text,
            level=1,
            source_chunk_ids=[chunk_id]
        )

        logger.info(
            f"External memory summarization completed for user {user_id}: "
            f"{len(messages)} messages archived to chunk {chunk_id}"
        )

        # Check if we need multi-level compression
        await self._check_multilevel_compression(user_id)

        return True

    async def _check_multilevel_compression(self, user_id: int) -> bool:
        """
        Check if multi-level compression is needed.

        When there are too many level-1 summaries, compress them into
        a higher-level summary.

        Returns:
            True if compression was performed
        """
        active_summaries = self.memory.get_active_summaries(user_id)

        if len(active_summaries) <= MAX_ACTIVE_SUMMARIES_TOTAL:
            return False

        # Count summaries by level
        level_counts: Dict[int, List[Summary]] = {}
        for summary in active_summaries:
            if summary.level not in level_counts:
                level_counts[summary.level] = []
            level_counts[summary.level].append(summary)

        # Check if level 1 summaries need compression
        level1_summaries = level_counts.get(1, [])

        if len(level1_summaries) > MAX_ACTIVE_LEVEL1_SUMMARIES:
            logger.info(
                f"Triggering level-2 compression for user {user_id}: "
                f"{len(level1_summaries)} level-1 summaries"
            )

            # Take oldest level-1 summaries to compress
            summaries_to_compress = sorted(
                level1_summaries,
                key=lambda s: s.created_at
            )[:MAX_ACTIVE_LEVEL1_SUMMARIES]

            # Generate meta-summary
            meta_summary_text = await self.generate_meta_summary(summaries_to_compress)

            if meta_summary_text is None:
                logger.error(
                    f"Meta-summarization failed for user {user_id}, "
                    "keeping level-1 summaries active"
                )
                return False

            # Archive the source summaries
            summary_ids = [s.id for s in summaries_to_compress]
            self.memory.archive_summaries(user_id, summary_ids)

            # Get source chunk IDs from compressed summaries
            source_chunks = []
            for s in summaries_to_compress:
                source_chunks.extend(s.source_chunk_ids)

            # Add level-2 summary
            self.memory.add_summary(
                user_id=user_id,
                summary_text=meta_summary_text,
                level=2,
                source_chunk_ids=source_chunks
            )

            logger.info(
                f"Level-2 compression completed for user {user_id}: "
                f"{len(summaries_to_compress)} level-1 summaries archived"
            )

            # Recursively check for even higher-level compression
            await self._check_multilevel_compression(user_id)

            return True

        # Check other levels similarly
        for level in sorted(level_counts.keys()):
            if level == 1:
                continue

            level_summaries = level_counts[level]
            if len(level_summaries) > MAX_ACTIVE_LEVEL1_SUMMARIES:
                logger.info(
                    f"Triggering level-{level+1} compression for user {user_id}"
                )

                summaries_to_compress = sorted(
                    level_summaries,
                    key=lambda s: s.created_at
                )[:MAX_ACTIVE_LEVEL1_SUMMARIES]

                meta_summary_text = await self.generate_meta_summary(summaries_to_compress)

                if meta_summary_text is None:
                    continue

                summary_ids = [s.id for s in summaries_to_compress]
                self.memory.archive_summaries(user_id, summary_ids)

                source_chunks = []
                for s in summaries_to_compress:
                    source_chunks.extend(s.source_chunk_ids)

                self.memory.add_summary(
                    user_id=user_id,
                    summary_text=meta_summary_text,
                    level=level + 1,
                    source_chunk_ids=source_chunks
                )

                logger.info(
                    f"Level-{level+1} compression completed for user {user_id}"
                )

                return True

        return False

    def get_status(self, user_id: int) -> Dict[str, Any]:
        """
        Get summarization status for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            Dictionary with status information
        """
        if self._use_external_memory(user_id):
            return self._get_status_external(user_id)
        else:
            return self._get_status_legacy(user_id)

    def _get_status_legacy(self, user_id: int) -> Dict[str, Any]:
        """Get status using legacy ConversationStore."""
        state = self.store.get_conversation_state(user_id)
        config = state.summary_config

        return {
            "enabled": config.enabled,
            "storage_type": "legacy",
            "memory_enabled": False,
            "message_threshold": config.message_threshold,
            "current_message_count": state.message_count,
            "total_messages_in_history": len(state.messages),
            "has_summary": state.summary is not None,
            "last_summary_at": state.last_summary_at,
            "messages_until_next_summary": (
                max(0, config.message_threshold - state.message_count)
                if config.enabled else None
            ),
            "active_summaries": 0,
            "max_summary_level": 0,
            "archived_messages": 0
        }

    def _get_status_external(self, user_id: int) -> Dict[str, Any]:
        """Get status using ExternalMemory."""
        config = self.memory.get_user_config(user_id)
        stats = self.memory.get_statistics(user_id)

        if config is None:
            return {
                "enabled": False,
                "storage_type": None,
                "memory_enabled": False,
                "message_threshold": 10,
                "current_message_count": 0,
                "total_messages_in_history": 0,
                "has_summary": False,
                "last_summary_at": None,
                "messages_until_next_summary": None,
                "active_summaries": 0,
                "max_summary_level": 0,
                "archived_messages": 0
            }

        messages_until_next = None
        if config.memory_enabled:
            messages_until_next = max(
                0,
                config.summary_every_n - stats["messages_since_last_summary"]
            )

        return {
            "enabled": config.memory_enabled,
            "storage_type": config.storage_type,
            "memory_enabled": config.memory_enabled,
            "message_threshold": config.summary_every_n,
            "current_message_count": stats["messages_since_last_summary"],
            "total_messages_in_history": stats["total_messages"],
            "has_summary": stats["active_summaries"] > 0,
            "last_summary_at": None,  # Would need to track this separately
            "messages_until_next_summary": messages_until_next,
            "active_summaries": stats["active_summaries"],
            "max_summary_level": stats["max_summary_level"],
            "archived_messages": stats["archived_messages"]
        }

    def enable_summarization(
        self,
        user_id: int,
        message_threshold: int,
        storage_type: str = "sqlite"
    ) -> None:
        """
        Enable summarization for a user with specified threshold.

        Args:
            user_id: Telegram user ID
            message_threshold: Number of messages before summarization
            storage_type: "sqlite" or "json" (for external memory)
        """
        # Set up external memory configuration
        config = UserConfig(
            user_id=user_id,
            storage_type=storage_type,
            summary_every_n=message_threshold,
            memory_enabled=True
        )
        self.memory.set_user_config(config)

        # Also set in legacy store for compatibility
        self.store.set_summary_config(
            user_id=user_id,
            enabled=True,
            message_threshold=message_threshold
        )

        logger.info(
            f"Summarization enabled for user {user_id}: "
            f"threshold={message_threshold}, storage={storage_type}"
        )

    def disable_summarization(self, user_id: int) -> None:
        """
        Disable summarization for a user.

        Keeps existing data but stops auto-summarization.

        Args:
            user_id: Telegram user ID
        """
        # Disable in external memory
        config = self.memory.get_user_config(user_id)
        if config:
            config.memory_enabled = False
            self.memory.set_user_config(config)

        # Also disable in legacy store
        self.store.set_summary_config(user_id=user_id, enabled=False)

        logger.info(f"Summarization disabled for user {user_id}")

    def enable_external_memory(self, user_id: int) -> None:
        """
        Enable external memory using existing config.

        Args:
            user_id: Telegram user ID
        """
        config = self.memory.get_user_config(user_id)
        if config:
            config.memory_enabled = True
            self.memory.set_user_config(config)
            logger.info(f"External memory enabled for user {user_id}")
        else:
            logger.warning(
                f"Cannot enable external memory for user {user_id}: no config found"
            )

    def update_threshold(self, user_id: int, message_threshold: int) -> None:
        """
        Update summarization threshold for a user.

        Args:
            user_id: Telegram user ID
            message_threshold: New threshold value
        """
        # Update in external memory
        config = self.memory.get_user_config(user_id)
        if config:
            config.summary_every_n = message_threshold
            self.memory.set_user_config(config)

        # Also update in legacy store
        self.store.set_summary_config(
            user_id=user_id,
            message_threshold=message_threshold
        )

        logger.info(
            f"Threshold updated for user {user_id}: {message_threshold}"
        )

    def update_storage_type(self, user_id: int, storage_type: str) -> None:
        """
        Update storage type for a user.

        Args:
            user_id: Telegram user ID
            storage_type: "sqlite" or "json"
        """
        config = self.memory.get_user_config(user_id)
        if config:
            config.storage_type = storage_type
            self.memory.set_user_config(config)
            logger.info(
                f"Storage type updated for user {user_id}: {storage_type}"
            )
        else:
            # Create new config
            new_config = UserConfig(
                user_id=user_id,
                storage_type=storage_type,
                summary_every_n=10,
                memory_enabled=False
            )
            self.memory.set_user_config(new_config)
            logger.info(
                f"New config created for user {user_id}: storage={storage_type}"
            )
