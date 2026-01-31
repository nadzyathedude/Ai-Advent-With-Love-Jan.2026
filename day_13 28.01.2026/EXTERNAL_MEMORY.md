# External Memory System

This document describes the external memory system that provides persistent conversation storage with intelligent archiving and retrieval.

## Overview

The external memory system allows the bot to:
- Persist all conversation messages across bot restarts
- Archive older messages without deleting them
- Create multi-level summaries for context compression
- Search and retrieve relevant information from stored history
- Build token-budgeted context for OpenAI API calls

## Key Design Principles

### 1. Never Delete, Only Archive

**Critical**: Messages are NEVER deleted from storage. When summarization occurs:
- Messages are marked as `is_active=0` (archived)
- Messages are assigned a `chunk_id` for grouping
- Original content remains fully accessible for search and retrieval

This ensures:
- Full conversation history is always available
- Search can access both active and archived messages
- Rollback or audit is possible at any time

### 2. Multi-Level Summarization

As conversation history grows, the system compresses it through multiple levels:

```
Level 1: Raw messages → Summary of messages (chunk)
Level 2: Multiple L1 summaries → Meta-summary
Level 3+: Multiple L2 summaries → Higher-level meta-summary
```

Each summarization:
- Archives source items (messages or summaries)
- Creates a new summary at the next level
- Keeps recent items active for local coherence

### 3. Token-Budgeted Context Assembly

Before each API call, the system builds context within token limits:
- Priority 1: Active summaries (highest level first)
- Priority 2: Recent active messages (last 4 turns)
- Priority 3: Retrieved snippets from archived messages (based on query relevance)

## Storage Options

### SQLite (Recommended)

File: `memory.db`

**Advantages:**
- Fast indexed queries
- Atomic transactions
- Efficient for large datasets
- FTS5 support for full-text search (future enhancement)

**Schema:**

```sql
-- User configuration
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    storage_type TEXT NOT NULL DEFAULT 'sqlite',
    summary_every_n INTEGER NOT NULL DEFAULT 10,
    memory_enabled INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Messages (never deleted, only archived)
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,           -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1,  -- 0 = archived
    chunk_id INTEGER,                       -- Groups archived messages
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Indexes for efficient queries
CREATE INDEX idx_messages_user_id ON messages(user_id);
CREATE INDEX idx_messages_user_active ON messages(user_id, is_active);
CREATE INDEX idx_messages_chunk ON messages(chunk_id);

-- Summaries (multi-level compression)
CREATE TABLE summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    summary_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    level INTEGER NOT NULL DEFAULT 1,      -- Compression level
    source_chunk_ids TEXT NOT NULL DEFAULT '[]',  -- JSON array
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Indexes for summaries
CREATE INDEX idx_summaries_user_id ON summaries(user_id);
CREATE INDEX idx_summaries_user_active ON summaries(user_id, is_active);
```

### JSON File

File: `memory.json`

**Advantages:**
- Human-readable format
- Easy to inspect and debug
- No external dependencies
- Simple backup (copy file)

**Structure:**

```json
{
  "users": {
    "123456789": {
      "user_id": 123456789,
      "storage_type": "json",
      "summary_every_n": 10,
      "memory_enabled": true,
      "created_at": "2024-01-15T10:30:00",
      "updated_at": "2024-01-15T12:00:00"
    }
  },
  "messages": {
    "123456789": [
      {
        "id": 1,
        "user_id": 123456789,
        "role": "user",
        "content": "Hello, what's the weather like?",
        "created_at": "2024-01-15T10:30:00",
        "is_active": false,
        "chunk_id": 1
      },
      {
        "id": 2,
        "user_id": 123456789,
        "role": "assistant",
        "content": "I don't have real-time weather data...",
        "created_at": "2024-01-15T10:30:05",
        "is_active": false,
        "chunk_id": 1
      }
    ]
  },
  "summaries": {
    "123456789": [
      {
        "id": 1,
        "user_id": 123456789,
        "summary_text": "You asked about weather...",
        "created_at": "2024-01-15T11:00:00",
        "level": 1,
        "source_chunk_ids": [1],
        "is_active": true
      }
    ]
  }
}
```

**Atomic Writes:**

To prevent corruption, JSON writes use a safe pattern:
1. Write to temporary file (`memory.json.tmp`)
2. Sync to disk
3. Atomically rename to target file

## How Messages Are Archived

### Trigger Rule

Summarization triggers when:
1. External memory is enabled for the user
2. Number of user messages since last summary >= threshold (N)
3. An assistant response has just been stored

**What counts as a "message"**: We count user turns only. A complete exchange (user + assistant) counts as 1 toward the threshold.

### Archival Process

When summarization triggers:

1. **Collect Messages**: Get all active messages without a chunk_id
2. **Generate Summary**: Call OpenAI with messages to create summary
3. **Get Chunk ID**: Assign next sequential chunk ID for this batch
4. **Archive Messages**: Set `is_active=0` and `chunk_id` for all messages
5. **Store Summary**: Create new level-1 summary record

```
Before:
messages: [A(active), B(active), C(active), D(active)]
summaries: []

After summarization with threshold=2:
messages: [A(archived, chunk=1), B(archived, chunk=1),
           C(archived, chunk=1), D(archived, chunk=1)]
summaries: [Summary1(level=1, chunks=[1], active)]
```

**Important**: Messages A, B, C, D still exist in storage. They're just marked as archived.

## Multi-Level Summarization

### When Level-2+ Summaries Are Created

When there are too many active level-1 summaries (default: >5), the system:
1. Takes the oldest level-1 summaries
2. Generates a meta-summary combining them
3. Archives the source summaries
4. Creates a level-2 summary

This process continues recursively for higher levels.

### Compression Thresholds

```python
MAX_ACTIVE_LEVEL1_SUMMARIES = 5   # Trigger L2 when exceeded
MAX_ACTIVE_SUMMARIES_TOTAL = 10   # Maximum active summaries
```

### Example Progression

```
Initial state:
- 50 messages, threshold=10
- 5 L1 summaries created (one per 10 messages)
- All summaries active

After 6th L1 summary created:
- L2 compression triggered
- 5 oldest L1 summaries archived
- 1 L2 summary created
- Current state: 1 L2 summary + 1 L1 summary (both active)

Long-term:
- Multiple L2 summaries accumulate
- Eventually L3 compression triggers
- Hierarchy grows as needed
```

## Retrieval System

### Context Assembly Pipeline

When building context for an API call:

```
1. System Prompt
   └── Base personality and instructions

2. Active Summaries
   └── Highest level first, then lower levels
   └── Token budget: ~2000 tokens

3. Retrieved Snippets (if query provided)
   └── Search archived messages by keywords
   └── Rank by relevance and recency
   └── Token budget: ~1500 tokens

4. Recent Active Messages
   └── Last 4 user+assistant pairs
   └── Token budget: ~3000 tokens

5. Current User Message
   └── The new message being processed
```

### Search Algorithm

1. **Extract Keywords**: Remove stop words, get significant terms
2. **Search Messages**: LIKE query (SQLite) or substring match (JSON)
3. **Rank Results**:
   - More keyword matches = higher priority
   - More recent = higher priority
4. **Filter Duplicates**: Skip messages already in active context
5. **Apply Budget**: Stop adding when token limit reached

### Token Budget Enforcement

Default budgets:
```python
DEFAULT_MAX_CONTEXT_TOKENS = 8000
DEFAULT_SUMMARY_BUDGET = 2000
DEFAULT_RECENT_MESSAGES_BUDGET = 3000
DEFAULT_RETRIEVED_SNIPPETS_BUDGET = 1500
DEFAULT_SYSTEM_PROMPT_BUDGET = 1500
```

If context exceeds budget:
1. Trim retrieved snippets first
2. Reduce recent messages if still over
3. Truncate older summaries as last resort

## User Commands

### `/summary` - Setup Flow

Interactive 2-step configuration:

**Step 1: Storage Type**
```
Bot: Choose storage format:
     [SQLite (recommended)] [JSON file]
```

**Step 2: Threshold**
```
Bot: After how many messages should I compress?
     Send a number 1-500.
User: 15
Bot: External memory configured!
     Storage: SQLite
     Threshold: 15 messages
```

### `/summary_status` - Check Status

Shows:
- Enabled/disabled state
- Storage type
- Compression threshold
- Messages since last summary
- Total/archived message counts
- Active summaries count
- Max compression level reached

### `/summary_on` and `/summary_off`

Toggle external memory without reconfiguring:
- `/summary_off`: Disables memory (data preserved)
- `/summary_on`: Re-enables with saved config

### `/summary_now` - Force Compression

Immediately triggers summarization regardless of threshold.
Useful for:
- Before long break in conversation
- When context feels too large
- Testing the system

## Persistence Guarantees

### Data Durability

- **SQLite**: Uses WAL mode for crash recovery
- **JSON**: Atomic writes prevent partial corruption
- **Config**: Stored in same backend as messages

### Cross-Restart State

On bot startup:
1. Initialize storage backends
2. Load user configs from persistent storage
3. Resume counters from stored state
4. No data loss between runs

## Error Handling

### Summarization Failures

If OpenAI API fails during summarization:
- Messages remain active (NOT archived)
- Counter is not reset
- Will retry on next threshold trigger
- User is notified of failure

### Storage Failures

If disk write fails:
- Bot continues operating in-memory
- User receives warning message
- Admin is logged about the error
- Retry on next operation

### Graceful Degradation

If external memory is unavailable:
- Falls back to legacy ConversationStore
- Limited context but still functional
- No data loss in active session

## Limitations and Assumptions

1. **Single-User Focus**: Designed for per-user isolation, not shared contexts
2. **Token Estimation**: Uses tiktoken or ~4 chars/token fallback
3. **Search Simplicity**: LIKE/substring only (no semantic search)
4. **Summary Quality**: Depends on OpenAI model quality
5. **Disk Space**: Never deletes, so storage grows over time

## File Locations

```
/day_10 22.01.2026/
├── memory.db          # SQLite database (if using SQLite)
├── memory.json        # JSON file (if using JSON)
├── external_memory.py # Storage backends
├── memory_retrieval.py # Search and context assembly
├── summary_manager.py # Summarization logic
└── bot.py             # Bot integration
```

## Future Enhancements

Potential improvements not yet implemented:
- Full-text search (FTS5) for SQLite
- Semantic search with embeddings
- Automatic cleanup of very old archives
- Export/import functionality
- Memory statistics dashboard
