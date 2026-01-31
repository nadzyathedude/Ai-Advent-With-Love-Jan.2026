"""
Memory Retrieval Module

Handles intelligent retrieval from external memory and context assembly
for OpenAI API calls with token budget enforcement.

Key features:
- Token-budgeted context assembly
- Priority-based inclusion (summaries > recent turns > retrieved snippets)
- Keyword-based search in archived messages
- Ranking by relevance and recency
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

from external_memory import (
    ExternalMemory,
    Message,
    Summary,
    get_external_memory
)

logger = logging.getLogger(__name__)

# Default token budgets
DEFAULT_MAX_CONTEXT_TOKENS = 8000  # Reserve for response
DEFAULT_SUMMARY_BUDGET = 2000
DEFAULT_RECENT_MESSAGES_BUDGET = 3000
DEFAULT_RETRIEVED_SNIPPETS_BUDGET = 1500
DEFAULT_SYSTEM_PROMPT_BUDGET = 1500

# How many recent message pairs to keep for local coherence
RECENT_TURNS_TO_KEEP = 4  # 4 user+assistant pairs = 8 messages


@dataclass
class RetrievedContext:
    """Context retrieved from external memory."""
    summaries: List[Summary] = field(default_factory=list)
    recent_messages: List[Message] = field(default_factory=list)
    retrieved_snippets: List[Message] = field(default_factory=list)
    total_tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summaries_count": len(self.summaries),
            "recent_messages_count": len(self.recent_messages),
            "retrieved_snippets_count": len(self.retrieved_snippets),
            "total_tokens": self.total_tokens
        }


class TokenCounter:
    """Counts tokens for text using tiktoken or estimation."""

    def __init__(self, model: str = "gpt-4o"):
        self.model = model
        self._encoding = None

        if TIKTOKEN_AVAILABLE:
            try:
                # Try to get encoding for the model
                if "gpt-4" in model or "gpt-3.5" in model:
                    self._encoding = tiktoken.encoding_for_model(model)
                else:
                    # Default to cl100k_base for newer models
                    self._encoding = tiktoken.get_encoding("cl100k_base")
            except Exception as e:
                logger.warning(f"Failed to load tiktoken encoding: {e}")
                self._encoding = None

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        if not text:
            return 0

        if self._encoding:
            try:
                return len(self._encoding.encode(text))
            except Exception:
                pass

        # Fallback: estimate ~4 characters per token
        return len(text) // 4

    def count_messages_tokens(self, messages: List[Dict[str, str]]) -> int:
        """Count tokens in a list of message dicts."""
        total = 0
        for msg in messages:
            # Each message has overhead of ~4 tokens for role/formatting
            total += 4
            total += self.count_tokens(msg.get("content", ""))
        return total


class MemoryRetrieval:
    """
    Handles retrieval from external memory and context assembly.

    Builds context for OpenAI API with token budget enforcement.
    """

    def __init__(
        self,
        external_memory: Optional[ExternalMemory] = None,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
        summary_budget: int = DEFAULT_SUMMARY_BUDGET,
        recent_messages_budget: int = DEFAULT_RECENT_MESSAGES_BUDGET,
        retrieved_budget: int = DEFAULT_RETRIEVED_SNIPPETS_BUDGET,
        system_prompt_budget: int = DEFAULT_SYSTEM_PROMPT_BUDGET
    ):
        self.memory = external_memory or get_external_memory()
        self.max_context_tokens = max_context_tokens
        self.summary_budget = summary_budget
        self.recent_messages_budget = recent_messages_budget
        self.retrieved_budget = retrieved_budget
        self.system_prompt_budget = system_prompt_budget
        self.token_counter = TokenCounter()

    def extract_keywords(self, text: str) -> List[str]:
        """Extract significant keywords from text for search."""
        # Remove common words and extract meaningful terms
        stop_words = {
            'и', 'в', 'на', 'с', 'по', 'для', 'это', 'как', 'что', 'я', 'ты',
            'мы', 'они', 'он', 'она', 'оно', 'но', 'а', 'или', 'не', 'да',
            'нет', 'так', 'же', 'бы', 'за', 'из', 'от', 'до', 'к', 'у',
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
            'would', 'could', 'should', 'may', 'might', 'must', 'shall',
            'can', 'need', 'to', 'of', 'in', 'for', 'on', 'with', 'at',
            'by', 'from', 'as', 'into', 'through', 'during', 'before',
            'after', 'above', 'below', 'between', 'under', 'again',
            'further', 'then', 'once', 'here', 'there', 'when', 'where',
            'why', 'how', 'all', 'each', 'few', 'more', 'most', 'other',
            'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same',
            'so', 'than', 'too', 'very', 'just', 'about', 'also'
        }

        # Extract words (alphanumeric sequences)
        words = re.findall(r'\b\w+\b', text.lower())

        # Filter out stop words and short words
        keywords = [
            word for word in words
            if word not in stop_words and len(word) > 2
        ]

        # Return unique keywords, preserve order
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)

        return unique_keywords[:10]  # Limit to top 10 keywords

    def retrieve_context(
        self,
        user_id: int,
        current_query: Optional[str] = None,
        include_search: bool = True
    ) -> RetrievedContext:
        """
        Retrieve relevant context from external memory.

        Args:
            user_id: Telegram user ID
            current_query: The current user message (for relevance search)
            include_search: Whether to search archived messages

        Returns:
            RetrievedContext with summaries, recent messages, and snippets
        """
        context = RetrievedContext()
        tokens_used = 0

        # 1. Get active summaries (highest priority)
        summaries = self.memory.get_active_summaries(user_id)
        for summary in summaries:
            summary_tokens = self.token_counter.count_tokens(summary.summary_text)
            if tokens_used + summary_tokens <= self.summary_budget:
                context.summaries.append(summary)
                tokens_used += summary_tokens
            else:
                # If adding this summary exceeds budget, try to fit partial
                break

        summary_tokens_used = tokens_used

        # 2. Get recent active messages (for local coherence)
        recent_messages = self.memory.get_active_messages(user_id)

        # Keep last N turns (user+assistant pairs)
        messages_to_keep = RECENT_TURNS_TO_KEEP * 2
        if len(recent_messages) > messages_to_keep:
            recent_messages = recent_messages[-messages_to_keep:]

        recent_tokens = 0
        for msg in recent_messages:
            msg_tokens = self.token_counter.count_tokens(msg.content) + 4
            if recent_tokens + msg_tokens <= self.recent_messages_budget:
                context.recent_messages.append(msg)
                recent_tokens += msg_tokens
            else:
                break

        tokens_used += recent_tokens

        # 3. Search for relevant snippets in archived messages (if query provided)
        if include_search and current_query:
            keywords = self.extract_keywords(current_query)

            if keywords:
                # Search for each keyword and collect results
                all_snippets: Dict[int, Message] = {}

                for keyword in keywords[:5]:  # Limit keyword searches
                    results = self.memory.search_messages(
                        user_id=user_id,
                        query=keyword,
                        include_inactive=True,
                        limit=5
                    )

                    for msg in results:
                        # Skip messages already in recent_messages
                        if msg.id not in {m.id for m in context.recent_messages}:
                            if msg.id not in all_snippets:
                                all_snippets[msg.id] = msg

                # Rank snippets by relevance (keyword match count) and recency
                def rank_snippet(msg: Message) -> tuple:
                    content_lower = msg.content.lower()
                    keyword_matches = sum(
                        1 for kw in keywords if kw in content_lower
                    )
                    return (-keyword_matches, -msg.created_at.timestamp())

                ranked_snippets = sorted(all_snippets.values(), key=rank_snippet)

                snippet_tokens = 0
                for msg in ranked_snippets:
                    msg_tokens = self.token_counter.count_tokens(msg.content) + 4
                    if snippet_tokens + msg_tokens <= self.retrieved_budget:
                        context.retrieved_snippets.append(msg)
                        snippet_tokens += msg_tokens
                    else:
                        break

                tokens_used += snippet_tokens

        context.total_tokens = tokens_used

        logger.debug(
            f"Retrieved context for user {user_id}: "
            f"{len(context.summaries)} summaries ({summary_tokens_used} tokens), "
            f"{len(context.recent_messages)} recent messages, "
            f"{len(context.retrieved_snippets)} snippets, "
            f"total {tokens_used} tokens"
        )

        return context

    def build_messages_for_api(
        self,
        user_id: int,
        system_prompt: str,
        current_message: Optional[str] = None,
        include_search: bool = True
    ) -> List[Dict[str, str]]:
        """
        Build message list for OpenAI API with external memory context.

        Args:
            user_id: Telegram user ID
            system_prompt: System prompt for the bot
            current_message: The current user message
            include_search: Whether to search archived messages for relevance

        Returns:
            List of message dicts for OpenAI API
        """
        messages = []

        # 1. System prompt
        messages.append({"role": "system", "content": system_prompt})

        # 2. Retrieve context from external memory
        context = self.retrieve_context(
            user_id=user_id,
            current_query=current_message,
            include_search=include_search
        )

        # 3. Add summaries as system context
        if context.summaries:
            summary_text = self._format_summaries(context.summaries)
            messages.append({
                "role": "system",
                "content": f"Context from conversation history:\n{summary_text}"
            })

        # 4. Add retrieved snippets as additional context
        if context.retrieved_snippets:
            snippets_text = self._format_snippets(context.retrieved_snippets)
            messages.append({
                "role": "system",
                "content": f"Relevant past exchanges:\n{snippets_text}"
            })

        # 5. Add recent messages
        for msg in context.recent_messages:
            messages.append({
                "role": msg.role,
                "content": msg.content
            })

        # 6. Add current message if provided and not already in recent
        if current_message:
            # Check if the current message is already the last message
            if not context.recent_messages or \
               context.recent_messages[-1].content != current_message:
                messages.append({
                    "role": "user",
                    "content": current_message
                })

        # Enforce total token budget
        messages = self._enforce_token_budget(messages)

        return messages

    def _format_summaries(self, summaries: List[Summary]) -> str:
        """Format summaries for inclusion in context."""
        if not summaries:
            return ""

        parts = []

        # Group by level
        levels = {}
        for summary in summaries:
            if summary.level not in levels:
                levels[summary.level] = []
            levels[summary.level].append(summary)

        # Format highest level first
        for level in sorted(levels.keys(), reverse=True):
            level_summaries = levels[level]
            if level > 1:
                parts.append(f"[High-level summary (compression level {level})]")

            for summary in level_summaries:
                parts.append(summary.summary_text)

        return "\n\n".join(parts)

    def _format_snippets(self, snippets: List[Message]) -> str:
        """Format retrieved snippets for inclusion in context."""
        if not snippets:
            return ""

        parts = []
        for msg in snippets:
            role_label = "User" if msg.role == "user" else "Assistant"
            # Truncate long snippets
            content = msg.content
            if len(content) > 500:
                content = content[:500] + "..."
            parts.append(f"{role_label}: {content}")

        return "\n---\n".join(parts)

    def _enforce_token_budget(
        self,
        messages: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """Ensure messages fit within token budget."""
        total_tokens = self.token_counter.count_messages_tokens(messages)

        if total_tokens <= self.max_context_tokens:
            return messages

        # Need to trim - remove from the middle (keep system and recent)
        logger.warning(
            f"Context exceeds budget ({total_tokens} > {self.max_context_tokens}), trimming"
        )

        # Strategy: keep first 2 messages (system prompts) and last N messages
        if len(messages) <= 4:
            return messages

        # Find system messages
        system_messages = []
        other_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_messages.append(msg)
            else:
                other_messages.append(msg)

        # Keep last few user/assistant exchanges
        while other_messages:
            test_messages = system_messages + other_messages
            tokens = self.token_counter.count_messages_tokens(test_messages)

            if tokens <= self.max_context_tokens:
                return test_messages

            # Remove oldest non-system message
            if other_messages:
                other_messages.pop(0)

        # If still over budget, trim system messages content
        return system_messages[:2] + other_messages[-4:]

    def get_context_summary(self, user_id: int) -> Dict[str, Any]:
        """Get a summary of what context is available for a user."""
        config = self.memory.get_user_config(user_id)
        stats = self.memory.get_statistics(user_id)

        if not config or not config.memory_enabled:
            return {
                "enabled": False,
                "message": "External memory is not enabled"
            }

        context = self.retrieve_context(user_id, include_search=False)

        return {
            "enabled": True,
            "storage_type": config.storage_type,
            "summary_every_n": config.summary_every_n,
            "active_summaries": len(context.summaries),
            "max_summary_level": stats["max_summary_level"],
            "recent_messages": len(context.recent_messages),
            "total_messages": stats["total_messages"],
            "archived_messages": stats["archived_messages"],
            "messages_until_next_summary": max(
                0,
                config.summary_every_n - stats["messages_since_last_summary"]
            ),
            "estimated_context_tokens": context.total_tokens
        }


# Global instance
_memory_retrieval: Optional[MemoryRetrieval] = None


def get_memory_retrieval() -> MemoryRetrieval:
    """Get or create the global MemoryRetrieval instance."""
    global _memory_retrieval
    if _memory_retrieval is None:
        _memory_retrieval = MemoryRetrieval()
    return _memory_retrieval


def init_memory_retrieval(
    external_memory: Optional[ExternalMemory] = None,
    **kwargs
) -> MemoryRetrieval:
    """Initialize and return the memory retrieval."""
    global _memory_retrieval
    _memory_retrieval = MemoryRetrieval(external_memory=external_memory, **kwargs)
    return _memory_retrieval
