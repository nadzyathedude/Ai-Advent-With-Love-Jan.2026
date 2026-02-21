# Standalone Agent Platform

A Python agent platform with plugin-based tool loading, per-agent permissions, LangGraph-style graph orchestration, and a CLI interface.

## Features

- **Plugin system** — Drop-in tool plugins with JSON manifests and YAML config
- **Permission enforcement** — Per-agent allow-lists checked at invocation time
- **Graph orchestration** — Directed graph execution with conditional routing
- **BM25 search** — Pure Python keyword search over project docs (no embeddings)
- **Continuous learning** — SQLite-backed review memory that improves over time
- **Product support agent** — RAG-powered support with CRM + conversation memory
- **Unified assistant** — RAG + MCP + task management + priority recommendations
- **Task manager** — SQLite-backed task CRUD with priorities, dependencies, and status tracking
- **MCP bridge** — Mock MCP service integrations (calendar, notifications, metrics)
- **Priority engine** — Rule-based weighted scoring for task prioritization
- **Zero AI dependencies** — Runs entirely locally, no external API calls

## Installation

```bash
cd "day_22 10.02.2026/"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Ask a question

```bash
python -m core.cli.main ask "What is the project architecture?"
python -m core.cli.main ask "What branch am I on?" --debug
```

### List loaded plugins

```bash
python -m core.cli.main list-plugins
```

### List registered tools

```bash
python -m core.cli.main list-tools
```

## Running Tests

```bash
python -m unittest discover tests/ -v
```

## Project Structure

```
core/
  registry/        # Tool ABC, ToolRegistry, PermissionChecker, PluginLoader
  orchestration/   # Graph engine, Node ABC, concrete nodes
  agents/          # Agent definitions (project_helper)
  cli/             # CLI entry point
agents/
  reviewers/       # Multi-agent PR review system + continuous learning
  support_agent.py # Product support agent (RAG + CRM)
  assistant_agent.py # Unified project assistant (RAG + MCP + Tasks + Priority)
plugins/
  docs_rag/        # BM25 documentation search
  git_context/     # Git branch info
  pr_context/      # PR diff and file content tools
  review_memory/   # SQLite-backed learning memory store
  crm/             # Simulated CRM with user/ticket data
  support_memory/  # Long-term conversation memory store
  task_manager/    # Task CRUD with SQLite (create, list, update, get, status)
  mcp_bridge/      # Mock MCP service integrations (calendar, notifications, metrics)
priority_engine.py # Rule-based weighted task scoring
llm_router.py      # Intent detection via keyword scoring
rag_module.py      # Thin wrapper for docs search
mcp_client.py      # Thin wrapper for MCP service calls
task_service.py    # Thin wrapper for task CRUD operations
assistant.py       # Standalone entry point for the assistant
config/
  plugins.yaml     # Plugin enable/disable
  agents.yaml      # Agent permission allow-lists
project/docs/      # Sample documentation (+ assistant.md)
project/faq/       # FAQ content for support agent
tests/             # Unit tests
```

## Configuration

### plugins.yaml

Enable or disable plugins:

```yaml
plugins:
  docs_rag:
    enabled: true
  git_context:
    enabled: true
  review_memory:
    enabled: true
  crm:
    enabled: true
  support_memory:
    enabled: true
  task_manager:
    enabled: true
  mcp_bridge:
    enabled: true
```

### agents.yaml

Define agent permissions:

```yaml
agents:
  project_helper:
    permissions:
      - "docs:read"
      - "git:read"
  review_orchestrator:
    permissions:
      - "pr:read"
      - "docs:read"
      - "review_memory:read"
      - "review_memory:write"
  support_agent:
    permissions:
      - "docs:read"
      - "crm:read"
      - "support_memory:read"
      - "support_memory:write"
  assistant_agent:
    permissions:
      - "docs:read"
      - "task:read"
      - "task:write"
      - "mcp:read"
```

## Multi-Agent PR Review System

Automated code review using specialized reviewer agents that analyze diffs in a graph pipeline with continuous learning.

### How it works

```
CLI "review" command / CI trigger
  → ReviewOrchestrator (Graph)
    → PRFetchNode           (fetches diff via pr.get_diff)
    → LearningContextNode   (queries review memory for historical patterns)
    → DocsContextNode       (fetches style docs via docs.search_project_docs)
    → BugReviewNode         (pattern-based bug detection)
    → StyleReviewNode       (style rule checking + docs context)
    → SecurityReviewNode    (security pattern scanning)
    → PerformanceReviewNode (perf anti-pattern detection)
    → ReviewMergeNode       (dedup, prioritize, compute risk, format report)
    → LearningAdjustNode    (applies learning: deprioritize false positives, boost confirmed)
    → MemoryPersistNode     (stores review run to SQLite memory)
    → END
```

Each agent has its own permissions enforced by the registry:
- `bug_reviewer` — `pr:read`
- `style_reviewer` — `pr:read`, `docs:read`
- `security_reviewer` — `pr:read`
- `performance_reviewer` — `pr:read`
- `learning_reviewer` — `review_memory:read`
- `review_orchestrator` — `pr:read`, `docs:read`, `review_memory:read`, `review_memory:write`

### Run a review locally

```bash
python -m core.cli.main review --base main
python -m core.cli.main review --base main --pr-id "myrepo#42" --debug
```

### Record feedback on findings

```bash
# Search past findings
python -m core.cli.main history --category bug --limit 10

# Mark a finding as accepted, rejected, fixed, or ignored
python -m core.cli.main feedback 42 accepted --comment "Good catch"
python -m core.cli.main feedback 15 rejected --comment "False positive in tests"
```

### What it detects

| Reviewer | Examples |
|----------|----------|
| **Bug** | Bare `except:`, mutable defaults, `== None`, `range(len(...))` |
| **Style** | Line length > 120, trailing whitespace, wildcard imports, missing docstrings |
| **Security** | `eval()`, hardcoded secrets, `shell=True`, SQL injection, `pickle.loads` |
| **Performance** | Nested loops, `.readlines()`, heavy module imports, `in list(...)` |

### Continuous Learning

The review system improves over time by storing findings in a SQLite database (`review_memory.db`):

- **False positive reduction** — Findings repeatedly rejected are auto-deprioritized
- **Priority boosting** — Findings repeatedly confirmed are severity-boosted
- **Convention tracking** — Project-specific patterns are stored and applied
- **Ephemeral fallback** — Runs with in-memory DB if persistent storage unavailable

Set `REVIEW_MEMORY_DB` env var to customize the database path.

### CI Integration

The `.github/workflows/pr-review.yml` workflow:
1. Downloads the learning DB artifact from previous runs (if available)
2. Runs the reviewer with continuous learning enabled
3. Uploads the updated learning DB as a GitHub Actions artifact
4. Posts the review report as a PR comment

## Product Support Agent

AI-powered product support that combines FAQ documentation (BM25 search), CRM user context, and long-term conversation memory to provide personalized answers.

### How it works

```
CLI "support" command
  → SupportAgent (Graph)
    → UserContextNode           (fetches user profile + tickets via crm.get_user_tickets)
    → MemoryRetrieveNode        (fetches past conversations via support_memory.get_user_history)
    → SupportDocsRetrieveNode   (searches FAQ docs via docs.search_project_docs)
    → ContextMergeNode          (combines CRM + memory + docs into analysis)
    → SupportAnswerComposerNode (formats final markdown response with history)
    → MemoryStoreNode           (persists interaction via support_memory.store_interaction)
    → END
```

The agent has four permissions enforced by the registry:
- `support_agent` — `docs:read`, `crm:read`, `support_memory:read`, `support_memory:write`

### Run a support query

```bash
python -m core.cli.main support --user-id 1 "Why does my login fail?"
python -m core.cli.main support --user-id 1 "How do I reset my password?" --debug
python -m core.cli.main support --user-id 3 "SSO integration not working"
```

### CRM Plugin

The CRM plugin provides a SQLite-backed simulated customer database with:
- **8 users** across free, pro, and enterprise plans
- **18 tickets** spanning categories: login, billing, api, integration, performance, general
- **40+ history entries** showing ticket progression

Tools:
- `crm.get_user_tickets` — Get user profile and their support tickets
- `crm.get_ticket_details` — Get full ticket with conversation history
- `crm.search_similar_issues` — Search tickets by keyword

Set `CRM_DB` env var to customize the database path.

### Conversation Memory

The support agent maintains long-term conversation memory in SQLite (`support_memory.db`):

- **Persistent storage** — Interactions persist across sessions
- **Auto-categorization** — Issues automatically tagged (auth, billing, api, performance, integration)
- **Auto-summarization** — Old interactions summarized when count exceeds 20 per user
- **Privacy controls** — Per-user isolation, `support-clear` command for deletion
- **Ephemeral fallback** — Runs with in-memory DB if persistent storage unavailable

Tools:
- `support_memory.store_interaction` — Store a conversation exchange
- `support_memory.get_user_history` — Retrieve recent history + summary
- `support_memory.search_past_issues` — Search past interactions by keyword

```bash
# View user interaction history
python -m core.cli.main support-history --user-id 1

# Delete user history (privacy)
python -m core.cli.main support-clear --user-id 1
```

Set `SUPPORT_MEMORY_DB` env var to customize the database path.

## Unified AI Project Assistant

A single conversational interface that combines RAG knowledge retrieval, MCP service integrations, task management CRUD, and a priority recommendation engine — all orchestrated via the graph engine with intent-based routing.

### How it works

```
CLI "assistant" command
  → AssistantAgent (Graph)
    → IntentRouterNode         (keyword scoring → knowledge/task_create/status/prioritize/combined)
    → [conditional routing based on intent]
      → RAGRetrieveNode        (BM25 docs search via docs.search_project_docs)
      → TaskParseNode          (extracts title, priority, effort from natural language)
      → TaskCreateNode         (creates task via task.create)
      → StatusFetchNode        (fetches task list + project status)
      → PriorityComputeNode    (weighted scoring: due_date + priority + blockers + effort + status)
      → MCPContextNode         (fetches notifications + metrics from MCP services)
    → ResponseComposerNode     (formats final markdown response)
    → END
```

The agent has four permissions enforced by the registry:
- `assistant_agent` — `docs:read`, `task:read`, `task:write`, `mcp:read`

### Run the assistant

```bash
# Knowledge query
python -m core.cli.main assistant "What is the project architecture?"

# Create a task
python -m core.cli.main assistant "Create a high priority task to fix login bug"

# Project status
python -m core.cli.main assistant "What is the current project status?"

# Priority recommendations
python -m core.cli.main assistant "Show high priority tasks and suggest what to do first"

# Direct task management
python -m core.cli.main task-list --priority high
python -m core.cli.main task-status
```

### Task Manager Plugin

SQLite-backed task CRUD with priorities, dependencies, and project status:
- **8 sample tasks** across various statuses, priorities, and effort levels
- **5 tools**: create, list, update, get, project_status

Set `TASK_MANAGER_DB` env var to customize the database path.

### MCP Bridge Plugin

Mock MCP service integrations:
- **Calendar** — today's events, next meeting, free slots
- **Notifications** — unread notifications, send messages
- **Metrics** — development summary (commits, PRs, issues), sprint velocity

### Priority Engine

Weighted scoring formula:

| Factor | Weight | Description |
|--------|--------|-------------|
| Due date | 0.30 | Urgency from deadline proximity |
| Priority level | 0.25 | Critical/high/medium/low mapping |
| Blocker count | 0.20 | How many tasks depend on this one |
| Effort | 0.15 | Smaller effort = quicker wins |
| Status | 0.10 | In-progress > todo > blocked |

### FAQ Documentation

FAQ content in `project/faq/` indexed by the BM25 search engine:
- `general.md` — Account creation, password reset, plan tiers, data export
- `billing.md` — Subscriptions, refunds, payment methods, invoices
- `api.md` — API auth, rate limits, webhooks, error codes, SDKs
- `troubleshooting.md` — Login/MFA issues, slow dashboard, integration errors

## Dependencies

- `pyyaml>=6.0`
