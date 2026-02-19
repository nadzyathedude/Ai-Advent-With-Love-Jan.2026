"""Tests for graph execution engine: linear, conditional, and END termination."""

import unittest

from core.orchestration.graph import END, Graph, GraphState
from core.orchestration.nodes import Node


class RecorderNode(Node):
    """Test node that records its execution in state."""

    def __init__(self, label: str):
        self.label = label

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        state.tools_used.append(self.label)
        return state


class RouteSetterNode(Node):
    """Test node that sets a route for conditional routing."""

    def __init__(self, route: list):
        self._route = route

    def execute(self, state: GraphState, registry, agent_id: str) -> GraphState:
        state.route = self._route
        return state


class TestLinearExecution(unittest.TestCase):
    """Test graph with static edges: A -> B -> C -> END."""

    def test_linear_graph(self):
        graph = Graph()
        graph.add_node("a", RecorderNode("A"))
        graph.add_node("b", RecorderNode("B"))
        graph.add_node("c", RecorderNode("C"))
        graph.set_entry_point("a")
        graph.add_edge("a", "b")
        graph.add_edge("b", "c")
        graph.add_edge("c", END)

        state = graph.run(GraphState())
        self.assertEqual(state.tools_used, ["A", "B", "C"])
        self.assertEqual(state.nodes_executed, ["a", "b", "c"])


class TestConditionalRouting(unittest.TestCase):
    """Test graph with conditional edges using route_next."""

    def test_conditional_skips_nodes(self):
        from core.orchestration.nodes import route_next

        graph = Graph()
        # Router sets route to only visit "b" then "c", skipping "a_extra"
        graph.add_node("router", RouteSetterNode(["b", "c"]))
        graph.add_node("b", RecorderNode("B"))
        graph.add_node("c", RecorderNode("C"))
        graph.set_entry_point("router")
        graph.add_conditional_edges("router", route_next)
        graph.add_conditional_edges("b", route_next)
        graph.add_edge("c", END)

        state = graph.run(GraphState())
        self.assertEqual(state.tools_used, ["B", "C"])
        self.assertIn("router", state.nodes_executed)
        self.assertIn("b", state.nodes_executed)
        self.assertIn("c", state.nodes_executed)

    def test_empty_route_goes_to_end(self):
        from core.orchestration.nodes import route_next

        graph = Graph()
        graph.add_node("router", RouteSetterNode([]))
        graph.set_entry_point("router")
        graph.add_conditional_edges("router", route_next)

        state = graph.run(GraphState())
        self.assertEqual(state.nodes_executed, ["router"])
        self.assertEqual(state.tools_used, [])


class TestEndTermination(unittest.TestCase):
    """Test that the graph stops at END."""

    def test_stops_at_end(self):
        graph = Graph()
        graph.add_node("a", RecorderNode("A"))
        graph.set_entry_point("a")
        graph.add_edge("a", END)

        state = graph.run(GraphState())
        self.assertEqual(state.nodes_executed, ["a"])

    def test_no_entry_point_raises(self):
        graph = Graph()
        with self.assertRaises(ValueError):
            graph.run(GraphState())


class TestFullPipeline(unittest.TestCase):
    """Integration test with the project_helper graph using real plugins."""

    def test_docs_question(self):
        from core.registry.tool_registry import ToolRegistry
        from core.registry.permissions import PermissionChecker
        from core.registry.plugin_loader import PluginLoader
        from core.agents.project_helper import ask

        checker = PermissionChecker()
        registry = ToolRegistry(permission_checker=checker)
        loader = PluginLoader()
        loader.load_tools(registry)

        answer = ask("What is the project architecture?", registry)
        self.assertIn("Relevant Documentation", answer)

    def test_git_question(self):
        from core.registry.tool_registry import ToolRegistry
        from core.registry.permissions import PermissionChecker
        from core.registry.plugin_loader import PluginLoader
        from core.agents.project_helper import ask

        checker = PermissionChecker()
        registry = ToolRegistry(permission_checker=checker)
        loader = PluginLoader()
        loader.load_tools(registry)

        answer = ask("What branch am I on?", registry)
        # Should at least contain git branch info or an error about git
        self.assertTrue(len(answer) > 0)


if __name__ == "__main__":
    unittest.main()
