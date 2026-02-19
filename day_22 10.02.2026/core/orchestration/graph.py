"""LangGraph-style graph execution engine with conditional routing."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

END = "__end__"


@dataclass
class GraphState:
    """Shared state passed through every node in the graph."""
    question: str = ""
    retrieved_docs: List[Dict[str, Any]] = field(default_factory=list)
    git_branch: str = ""
    errors: List[str] = field(default_factory=list)
    final_answer: str = ""
    route: List[str] = field(default_factory=list)
    nodes_executed: List[str] = field(default_factory=list)
    tools_used: List[str] = field(default_factory=list)


class Graph:
    """Executes a DAG of nodes with static and conditional edges."""

    def __init__(self):
        self._nodes: Dict[str, Any] = {}  # name -> Node instance
        self._edges: Dict[str, str] = {}  # from -> to (static)
        self._conditional_edges: Dict[str, Callable] = {}  # from -> routing fn
        self._entry_point: Optional[str] = None

    def add_node(self, name: str, node: Any) -> None:
        self._nodes[name] = node

    def set_entry_point(self, name: str) -> None:
        self._entry_point = name

    def add_edge(self, from_node: str, to_node: str) -> None:
        self._edges[from_node] = to_node

    def add_conditional_edges(self, from_node: str, route_fn: Callable) -> None:
        self._conditional_edges[from_node] = route_fn

    def run(self, state: GraphState, registry=None, agent_id: str = "") -> GraphState:
        """Execute the graph starting from the entry point."""
        if self._entry_point is None:
            raise ValueError("No entry point set")

        current = self._entry_point
        while current != END:
            node = self._nodes.get(current)
            if node is None:
                state.errors.append(f"Node '{current}' not found in graph")
                break
            state = node.execute(state, registry, agent_id)
            state.nodes_executed.append(current)

            # Determine next node
            if current in self._edges:
                current = self._edges[current]
            elif current in self._conditional_edges:
                route_fn = self._conditional_edges[current]
                current = route_fn(state)
            else:
                break  # No outgoing edge — stop

        return state
