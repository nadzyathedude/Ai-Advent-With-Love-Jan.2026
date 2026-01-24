# Dialog Summarization Feature

This document describes the automatic dialogue compression (summarization) feature in the Telegram GPT bot.

## Overview

The bot can automatically compress conversation history by generating summaries after a configurable number of messages. This helps:

- Reduce context size sent to OpenAI API
- Lower API costs for long conversations
- Maintain conversation continuity while keeping relevant context
- Improve response quality by focusing on important information

## Commands

| Command | Description |
|---------|-------------|
| `/summary` | Start interactive setup to configure summarization |
| `/summary_status` | Show current summarization status and settings |
| `/summary_off` | Disable automatic summarization (keeps existing history) |
| `/summary_now` | Force summarization immediately |
| `/clear_history` | Clear all conversation history |

## Message Counting Policy

**A "message" is counted as one user+assistant turn pair.**

This means:
- When you send a message and receive a response, that counts as 1 message
- If you set N=10, summarization triggers after 10 complete exchanges
- Only completed exchanges are counted (user message + assistant response)

This approach ensures:
- Summarization only happens after the bot has responded
- Conversation continuity is never broken mid-exchange

## Summarization Trigger

Summarization is triggered when:
1. Summarization is enabled for the user (`/summary` configured)
2. Message count reaches the configured threshold N
3. An assistant response has just been completed

**Important**: Summarization never happens in the middle of a response. It only triggers after successfully sending a reply to the user.

## Summary Generation

The summary is generated using OpenAI's GPT-4o-mini model (cost-effective choice).

### What the Summary Preserves

1. **User's goals and preferences** expressed in the conversation
2. **Key decisions** made and instructions given
3. **Important facts** (names, dates, numbers, specific details)
4. **Unresolved questions** or pending next steps
5. **Overall context** needed to continue the conversation naturally

### Summary Prompt

The summarization uses a dedicated prompt that:
- Writes in second person ("You discussed...", "You asked about...")
- Keeps summaries to 200-400 words
- Uses bullet points for key items
- Focuses on information needed to continue the conversation

## Context Retention

After summarization:
1. The last 2 message pairs (4 messages) are retained for immediate continuity
2. A summary is stored and prepended to future OpenAI calls
3. The message counter resets to 0

### How Context is Built for OpenAI

```
[System Prompt]
[Summary (if exists): "Conversation summary so far: ..."]
[Recent messages (last 4)]
```

If multiple summarizations occur, summaries are concatenated with separators.

## Data Storage

### Database: `conversations.db`

Two tables are used:

#### `conversation_history`
| Column | Type | Description |
|--------|------|-------------|
| user_id | INTEGER | Primary key, Telegram user ID |
| messages | TEXT | JSON array of messages |
| summary | TEXT | Current accumulated summary |
| message_count | INTEGER | Messages since last compression |
| last_summary_at | TIMESTAMP | When last summarization occurred |
| updated_at | TIMESTAMP | Last update time |

#### `summary_config`
| Column | Type | Description |
|--------|------|-------------|
| user_id | INTEGER | Primary key, Telegram user ID |
| enabled | INTEGER | 1 if enabled, 0 if disabled |
| message_threshold | INTEGER | N - messages before summarization |
| updated_at | TIMESTAMP | Last update time |

### Data Isolation

Each user has completely independent:
- Conversation history
- Summary configuration
- Summary content

No user can access another user's data.

## Configuration Limits

| Setting | Minimum | Maximum | Default |
|---------|---------|---------|---------|
| Message threshold (N) | 1 | 500 | 10 |

Recommended threshold: 10-20 messages for typical conversations.

## Error Handling

### Summarization Failure

If summarization fails (e.g., OpenAI API error):
1. Original history is preserved (not deleted)
2. An error is logged
3. Summarization will be attempted again after next N messages

### Invalid Input

During `/summary` setup:
- Non-numeric input: prompts to enter a number
- Out of range: prompts with valid range (1-500)
- User can cancel with `/cancel`

## Observability

### Logging

The system logs (without sensitive content):
- Summarization events: user ID, message count, timestamp
- Configuration changes: user ID, new settings
- Errors: failures with details

Example log entries:
```
INFO - Summarization triggered for user 12345: 10 messages at 2026-01-24T12:00:00
INFO - Summary generated: 10 messages -> 350 chars, model=gpt-4o-mini
INFO - Summary applied for user 12345: kept 4 messages, reset counter
```

## Limitations and Edge Cases

### Limitations

1. **First message after clear**: No context available until conversation builds up
2. **Very long individual messages**: May still consume significant tokens even with summarization
3. **Rapid-fire messages**: Counter only increments after assistant responds
4. **Summary quality**: Depends on GPT-4o-mini's summarization capability

### Edge Cases

1. **User disables mid-count**: Counter is preserved, will continue if re-enabled
2. **Empty history on `/summary_now`**: Gracefully handled with message
3. **Threshold change**: Takes effect immediately for next count check
4. **Multiple quick messages**: All added to history, but counter only increments on assistant response

## Architecture

### Modules

```
bot.py                   # Main bot, command handlers
conversation_store.py    # Storage for history, summary, config
summary_manager.py       # Summarization logic and OpenAI calls
```

### Flow

```
User Message
    │
    ▼
Store user message
    │
    ▼
Build context (system + summary + history)
    │
    ▼
Call OpenAI for response
    │
    ▼
Store assistant message
    │
    ▼
Send response to user
    │
    ▼
Check if should_summarize (enabled && count >= N)
    │
    ├─► Yes: Generate summary, apply, reset counter
    │
    └─► No: Continue
```

## Cost Considerations

- Summarization uses GPT-4o-mini (cheapest capable model)
- Summary generation: ~500-800 tokens per call
- Savings increase with longer conversations
- Recommended threshold: balance between context quality and cost

For a conversation with N=10:
- Without summarization: context grows linearly with each message
- With summarization: context stays bounded to ~summary + 4 recent messages
