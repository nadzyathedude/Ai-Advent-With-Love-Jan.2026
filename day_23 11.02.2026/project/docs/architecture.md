# Agent Platform Architecture

## Overview

The Agent Platform is a standalone Python framework for building autonomous agents with plugin-based tool loading, per-agent permissions, and graph-based orchestration. It requires no external AI services and runs entirely locally.

## Core Components

### Tool Registry

The tool registry is the central component for managing tools. Each tool extends the `Tool` abstract base class and declares its name, description, and required permissions. The `ToolRegistry` stores tool instances and provides permission-checked invocation via the `invoke()` method.

### Plugin System

Plugins are self-contained packages in the `plugins/` directory. Each plugin contains a `plugin.json` manifest declaring its ID, version, entrypoint module, and tool definitions. The `PluginLoader` scans this directory, validates manifests, and uses `importlib.import_module` to dynamically load tool classes.

Plugin enablement is controlled via `config/plugins.yaml`. Only plugins marked as `enabled: true` are loaded.

### Permission System

The permission system enforces per-agent access control. Each agent has a list of allowed permissions defined in `config/agents.yaml`. When a tool is invoked, the `PermissionChecker` verifies that the calling agent has all required permissions before execution proceeds. Missing permissions raise a `PermissionDeniedError`.

### Graph Orchestration Engine

The orchestration engine implements a LangGraph-style directed graph execution model. A `Graph` contains named nodes connected by static edges and conditional routing functions.

Execution begins at the entry point and proceeds through nodes sequentially. Each node receives the shared `GraphState`, modifies it, and returns the updated state. Static edges connect nodes directly, while conditional edges use routing functions to determine the next node based on state.

The `GraphState` dataclass carries the question, retrieved documents, git context, errors, final answer, route plan, and execution history through the graph.

### Router Node

The `RouterNode` analyzes the user's question using keyword matching to determine which tools and nodes are relevant. It populates the `state.route` list with the names of nodes to visit. The `route_next()` function then acts as a conditional routing function, selecting the first unvisited node from the route.

## Data Flow

1. User submits a question via the CLI
2. The `RouterNode` sets the execution route based on question keywords
3. Data-gathering nodes (docs retrieval, git context) execute in route order
4. Each node calls its corresponding tool via the registry
5. The `AnswerComposerNode` formats the collected state into a readable answer
6. The final answer is displayed to the user

## Plugin Architecture

Each plugin follows a standard structure:

```
plugins/plugin_name/
  __init__.py
  plugin.json      # Manifest with id, version, entrypoint, tools
  tool_module.py   # Tool implementation class
```

The manifest schema requires:
- `id`: Unique plugin identifier
- `version`: Semantic version string
- `entrypoint`: Python module name (without .py)
- `tools`: Array of tool definitions with name, class, and permissions

## Security Model

The platform follows a principle of least privilege. Agents only have access to tools whose required permissions match their allow-list. Permission checks happen at invocation time in `ToolRegistry.invoke()`, ensuring no tool can be called without proper authorization.
