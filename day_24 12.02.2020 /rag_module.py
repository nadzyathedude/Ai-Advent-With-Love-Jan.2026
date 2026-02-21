"""RAG module — thin wrapper around the docs.search_project_docs tool.

Provides a clean interface for the assistant agent to query documentation
via the tool registry.
"""

from typing import Any, Dict, List

from core.registry.tool_registry import ToolResult


def search_docs(registry, agent_id: str, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Search project documentation via the docs_rag plugin.

    Returns a list of {text, source_path, score} dicts, or empty list on failure.
    """
    if registry is None:
        return []
    result: ToolResult = registry.invoke(
        "docs.search_project_docs", agent_id, query=query, top_k=top_k
    )
    if result.success and result.data:
        return result.data
    return []
