# Unified AI Project Assistant

The assistant agent combines RAG knowledge retrieval, MCP service integrations, task management CRUD, and a priority recommendation engine into a single conversational interface.

## Architecture

The assistant uses intent-based routing to direct queries through the appropriate pipeline nodes:

```
User Query → IntentRouterNode → [conditional routing] → ResponseComposerNode → END
```

### Intents

| Intent | Description | Nodes |
|--------|-------------|-------|
| **knowledge** | Documentation/architecture questions | RAGRetrieve |
| **task_create** | Create a new task | TaskParse → TaskCreate |
| **status** | Project/task status inquiry | StatusFetch |
| **prioritize** | Priority recommendations | StatusFetch → PriorityCompute |
| **combined** | Multiple intents detected | All relevant nodes |

### Nodes

- **IntentRouterNode** — Detects intent via keyword scoring, sets execution route
- **RAGRetrieveNode** — Searches project docs using BM25
- **TaskParseNode** — Extracts task title, priority, effort from natural language
- **TaskCreateNode** — Creates a task in the task manager
- **StatusFetchNode** — Fetches task list and project status
- **PriorityComputeNode** — Computes priority scores using weighted formula
- **MCPContextNode** — Fetches notifications and metrics from MCP services
- **ResponseComposerNode** — Formats the final markdown response

## Priority Engine

Tasks are scored using a weighted formula:

| Factor | Weight | Description |
|--------|--------|-------------|
| Due date | 0.30 | Urgency from deadline proximity |
| Priority level | 0.25 | Critical/high/medium/low mapping |
| Blocker count | 0.20 | How many tasks depend on this one |
| Effort | 0.15 | Smaller effort = quicker wins |
| Status | 0.10 | In-progress > todo > blocked |

## MCP Services

The assistant integrates with mock MCP services:

- **Calendar** — Today's events, next meeting, free slots
- **Notifications** — Unread notifications, send messages
- **Metrics** — Development summary, sprint velocity

## Usage

```bash
# Knowledge query
python -m core.cli.main assistant "What is the project architecture?"

# Create a task
python -m core.cli.main assistant "Create a high priority task to fix login bug"

# Project status
python -m core.cli.main assistant "What is the current project status?"

# Priority recommendations
python -m core.cli.main assistant "Show high priority tasks and suggest what to do first"

# Task management
python -m core.cli.main task-list --priority high
python -m core.cli.main task-status
```

## Permissions

The assistant agent requires: `docs:read`, `task:read`, `task:write`, `mcp:read`
