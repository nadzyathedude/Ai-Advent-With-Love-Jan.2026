# Task Tracker MCP Integration

This document describes the Task Tracker MCP server and its integration with the Telegram bot.

## Architecture Overview

```
┌─────────────────────┐         MCP (stdio)        ┌────────────────────────┐
│                     │◀───────────────────────────│                        │
│  Task Tracker       │         JSON-RPC           │  Telegram Bot          │
│  MCP Server         │───────────────────────────▶│  (MCP Client)          │
│                     │                            │                        │
└─────────┬───────────┘                            └────────────────────────┘
          │                                                    │
          ▼                                                    ▼
   ┌──────────────┐                                    ┌──────────────┐
   │  tasks.db    │                                    │  Telegram    │
   │  (SQLite)    │                                    │  Users       │
   └──────────────┘                                    └──────────────┘
```

### Components

1. **Task Tracker MCP Server** (`task_tracker_server.py`)
   - Standalone Python server using MCP protocol
   - Exposes task management tools via stdio transport
   - Persists tasks to SQLite database (`tasks.db`)

2. **Task Tracker MCP Client** (`task_tracker_client.py`)
   - Client module for the Telegram bot
   - Spawns the MCP server as subprocess
   - Communicates via stdin/stdout (MCP stdio transport)

3. **Telegram Bot** (`bot.py`)
   - Provides user-facing commands
   - Calls MCP tools through the client module
   - Displays results to users

## MCP Tools

The Task Tracker server exposes these tools:

| Tool Name | Description | Parameters |
|-----------|-------------|------------|
| `task_create` | Create a new task | `user_id` (required), `title` (required), `description` (optional) |
| `task_list_open` | List all open tasks for a user | `user_id` (required) |
| `task_get_open_count` | Get count of open tasks | `user_id` (optional) |
| `task_complete` | Mark a task as completed | `user_id` (required), `task_id` (required) |

## Installation

### Requirements

```bash
pip install -r requirements.txt
```

The `mcp>=1.0.0` package provides both server and client functionality.

### Database

The SQLite database is created automatically on first run at `tasks.db`.

Schema:
```sql
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    UNIQUE(user_id, title)
);
```

## Usage

### Starting the MCP Server (Standalone)

The MCP server can be tested standalone:

```bash
# Run the server (it will wait for MCP commands on stdin)
python task_tracker_server.py
```

For testing, you can use the MCP inspector or send JSON-RPC commands.

### Running the Telegram Bot

The bot automatically spawns the MCP server when needed:

```bash
python bot.py
```

### Telegram Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/tasks` | Show count of open tasks | `/tasks` → "Open tasks: 5" |
| `/task_add <title>` | Create a new task | `/task_add Buy groceries` |
| `/task_add <title> \| <desc>` | Create task with description | `/task_add Buy groceries \| Milk, bread, eggs` |
| `/task_list` | List all open tasks | Shows numbered list |
| `/task_done <id>` | Complete a task | `/task_done 3` |
| `/task_tools` | Show MCP tools | Lists available tools |

## Example Interaction

### 1. Create Tasks

```
User: /task_add Learn MCP protocol
Bot:  Task created!
      ID: 1
      Title: Learn MCP protocol

User: /task_add Build Task Tracker | Implement MCP server with SQLite
Bot:  Task created!
      ID: 2
      Title: Build Task Tracker
      Description: Implement MCP server with SQLite

User: /task_add Write documentation
Bot:  Task created!
      ID: 3
      Title: Write documentation
```

### 2. Check Open Tasks Count

```
User: /tasks
Bot:  Open tasks: 3

      Use /task_list to see all tasks.
      Use /task_add <title> to add a new task.
```

### 3. List Tasks

```
User: /task_list
Bot:  Open Tasks (3):

      1. Learn MCP protocol
      2. Build Task Tracker
         Implement MCP server with SQLite
      3. Write documentation

      Use /task_done <id> to complete a task.
```

### 4. Complete a Task

```
User: /task_done 1
Bot:  Task 1 marked as completed!

User: /tasks
Bot:  Open tasks: 2
```

### 5. View MCP Tools

```
User: /task_tools
Bot:  Task Tracker MCP Tools:

      1. task_create
         Create a new task for tracking

      2. task_list_open
         List all open (not completed) tasks for a user

      3. task_get_open_count
         Get the count of open tasks

      4. task_complete
         Mark a task as completed
```

## MCP Protocol Details

### Transport

Uses **stdio** transport - the bot spawns the server as a subprocess and communicates via stdin/stdout.

### Message Format

Standard MCP JSON-RPC 2.0 format:

**Request (tools/list):**
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
}
```

**Response:**
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "tools": [
            {
                "name": "task_get_open_count",
                "description": "Get the count of open tasks",
                "inputSchema": {...}
            }
        ]
    }
}
```

**Request (tools/call):**
```json
{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
        "name": "task_get_open_count",
        "arguments": {"user_id": "123456"}
    }
}
```

**Response:**
```json
{
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
        "content": [
            {
                "type": "text",
                "text": "{\"count\": 5, \"user_id\": \"123456\"}"
            }
        ]
    }
}
```

## Error Handling

The client handles these error cases:

1. **Server not found** - Python interpreter or script not available
2. **Connection timeout** - Server takes too long to respond
3. **Invalid response** - Malformed JSON or missing data
4. **Tool error** - Server returns an error in the result

All errors are logged and displayed to the user with a descriptive message.

## Files

```
day_12 27.01.2026/
├── task_tracker_server.py   # MCP server implementation
├── task_tracker_client.py   # MCP client for the bot
├── bot.py                   # Telegram bot (updated)
├── tasks.db                 # SQLite database (auto-created)
└── TASK_TRACKER_MCP.md      # This documentation
```
