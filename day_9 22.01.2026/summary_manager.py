"""
Summary Manager Module

Handles dialogue summarization using OpenAI.
Decides when to summarize, generates summaries, and manages the compression process.
"""

import logging
from datetime import datetime
from typing import Optional

from openai import OpenAI

from conversation_store import ConversationStore, ConversationState, get_conversation_store

logger = logging.getLogger(__name__)

# Model used for summarization (cheaper model for cost efficiency)
SUMMARIZATION_MODEL = "gpt-4o-mini"

# Summarization prompt template
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

# Number of recent messages to retain for continuity after summarization
MESSAGES_TO_RETAIN = 2


class SummaryManager:
    """
    Manages the summarization process for conversations.

    Works with ConversationStore to decide when to summarize,
    generate summaries via OpenAI, and apply them to conversation state.
    """

    def __init__(
        self,
        openai_client: OpenAI,
        conversation_store: Optional[ConversationStore] = None,
        summarization_model: str = SUMMARIZATION_MODEL,
        messages_to_retain: int = MESSAGES_TO_RETAIN
    ):
        """
        Initialize SummaryManager.

        Args:
            openai_client: OpenAI client instance
            conversation_store: ConversationStore instance (uses global if not provided)
            summarization_model: Model to use for summarization
            messages_to_retain: Number of recent turns to keep after summarization
        """
        self.client = openai_client
        self.store = conversation_store or get_conversation_store()
        self.summarization_model = summarization_model
        self.messages_to_retain = messages_to_retain

    def should_summarize(self, user_id: int) -> bool:
        """
        Check if summarization should be triggered for user.

        Args:
            user_id: Telegram user ID

        Returns:
            True if summarization should occur
        """
        return self.store.should_summarize(user_id)

    def format_messages_for_summary(self, messages: list[dict]) -> str:
        """
        Format conversation messages for the summarization prompt.

        Args:
            messages: List of message dicts with 'role' and 'content'

        Returns:
            Formatted string representation of the conversation
        """
        lines = []
        for msg in messages:
            role = msg["role"].upper()
            content = msg["content"]
            lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    async def generate_summary(self, messages: list[dict]) -> Optional[str]:
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
                    {"role": "system", "content": "You are a helpful assistant that creates conversation summaries."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800,
                temperature=0.3  # Lower temperature for more focused summaries
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
        messages = self.store.get_messages_for_summarization(user_id)

        if not messages:
            logger.warning(f"No messages to summarize for user {user_id}")
            return False

        # Log summarization event (without sensitive content)
        logger.info(
            f"Summarization triggered for user {user_id}: "
            f"{len(messages)} messages at {datetime.now().isoformat()}"
        )

        summary = await self.generate_summary(messages)

        if summary is None:
            # Summarization failed - keep original history and try later
            logger.error(
                f"Summarization failed for user {user_id}, "
                "keeping original history"
            )
            return False

        # Apply summary and update conversation state
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

    def get_status(self, user_id: int) -> dict:
        """
        Get summarization status for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            Dictionary with status information
        """
        state = self.store.get_conversation_state(user_id)
        config = state.summary_config

        return {
            "enabled": config.enabled,
            "message_threshold": config.message_threshold,
            "current_message_count": state.message_count,
            "total_messages_in_history": len(state.messages),
            "has_summary": state.summary is not None,
            "last_summary_at": state.last_summary_at,
            "messages_until_next_summary": (
                max(0, config.message_threshold - state.message_count)
                if config.enabled else None
            )
        }

    def enable_summarization(
        self,
        user_id: int,
        message_threshold: int
    ) -> None:
        """
        Enable summarization for a user with specified threshold.

        Args:
            user_id: Telegram user ID
            message_threshold: Number of messages before summarization
        """
        self.store.set_summary_config(
            user_id=user_id,
            enabled=True,
            message_threshold=message_threshold
        )
        logger.info(
            f"Summarization enabled for user {user_id} "
            f"with threshold={message_threshold}"
        )

    def disable_summarization(self, user_id: int) -> None:
        """
        Disable summarization for a user.

        Keeps existing conversation context but stops auto-summarization.

        Args:
            user_id: Telegram user ID
        """
        self.store.set_summary_config(user_id=user_id, enabled=False)
        logger.info(f"Summarization disabled for user {user_id}")

    def update_threshold(self, user_id: int, message_threshold: int) -> None:
        """
        Update summarization threshold for a user.

        Args:
            user_id: Telegram user ID
            message_threshold: New threshold value
        """
        self.store.set_summary_config(
            user_id=user_id,
            message_threshold=message_threshold
        )
