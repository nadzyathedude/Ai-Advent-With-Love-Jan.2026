# Token Counting and Cost Estimation

This document explains how token counting and cost estimation work in the Telegram GPT bot.

## Overview

The bot tracks token usage for each interaction and can display a usage report to users after each model response. This report includes:
- Input (prompt) tokens
- Output (completion) tokens
- Total tokens
- Estimated costs in USD

## Token Counting Methods

### Primary Method: OpenAI API Usage Data (Preferred)

When making a request to the OpenAI API, the response includes usage information:

```python
response.usage.prompt_tokens      # Input tokens
response.usage.completion_tokens  # Output tokens
response.usage.total_tokens       # Total tokens
```

This is the **source of truth** for token counts as it reflects exactly what OpenAI counted and billed for.

### Fallback Method: Local Estimation with tiktoken

If API usage data is unavailable (e.g., streaming responses, API errors), the bot falls back to local token estimation using the `tiktoken` library.

**Encoding mappings:**
| Model | tiktoken Encoding |
|-------|-------------------|
| gpt-4o | o200k_base |
| gpt-4.1 | o200k_base |
| gpt-4.1-mini | o200k_base |
| gpt-3.5-turbo | cl100k_base |

**Input token estimation:**
- System prompt tokens + User message tokens

**Output token estimation:**
- Assistant response tokens

If tiktoken fails, a rough estimate of ~4 characters per token is used as a last resort.

## Cost Calculation

### Formula

```
cost_input = (input_tokens / 1,000,000) * input_price_per_1M
cost_output = (output_tokens / 1,000,000) * output_price_per_1M
total_cost = cost_input + cost_output
```

### Price Table (USD per 1M tokens)

| Model | Input Price | Output Price |
|-------|-------------|--------------|
| gpt-4o | $2.50 | $10.00 |
| gpt-4.1 | $2.00 | $8.00 |
| gpt-4.1-mini | $0.40 | $1.60 |
| gpt-3.5-turbo | $0.50 | $1.50 |

**Note:** Prices are approximate and may change. Check OpenAI's pricing page for current rates.

If a model is not found in the price table, costs are set to $0.00 and marked as "N/A (price unknown)" in the report.

## Usage Report Format

After each model response, if token reporting is enabled, the bot sends a second message:

```
**Token Usage** (GPT-4o, API):
  Input: 150 tokens
  Output: 200 tokens
  Total: 350 tokens

**Cost (USD):**
  Input: $0.000375
  Output: $0.002000
  Total: $0.002375
```

The source indicator shows:
- `API` - Token counts from OpenAI API (accurate)
- `estimate` - Token counts estimated locally (approximate)

## User Commands

### `/tokens` - Show current status
```
**Отчёт о токенах:** включён

Используйте:
• `/tokens on` — включить отчёт
• `/tokens off` — выключить отчёт
```

### `/tokens on` - Enable token reporting
Enables the usage report after each response.

### `/tokens off` - Disable token reporting
Disables the usage report. The main response is still sent.

## Per-User Settings

Token reporting preferences are stored per-user in SQLite database:
- Default: **enabled** (show tokens)
- Setting persists across bot restarts
- Each user can have their own preference

## Assumptions and Limitations

1. **Pricing accuracy:** Prices are hardcoded and may not reflect current OpenAI pricing. Update `models.py` when prices change.

2. **Token estimation accuracy:** Local tiktoken estimation may differ slightly from API counts due to:
   - Different handling of special tokens
   - Model-specific tokenization nuances

3. **Input token scope:** Input token count includes:
   - System prompt
   - User message
   - Does NOT include conversation history (bot uses single-turn mode)

4. **Cached tokens:** The bot does not currently track or display cached tokens (available in some OpenAI responses).

5. **Reasoning tokens:** For models with reasoning (e.g., o1), reasoning tokens are not separately tracked.

## Examples

### Example 1: Short interaction

**User message:** "Привет!"
**System prompt:** ~300 tokens
**Response:** ~50 tokens

```
**Token Usage** (GPT-4o, API):
  Input: 45 tokens
  Output: 12 tokens
  Total: 57 tokens

**Cost (USD):**
  Input: $0.000113
  Output: $0.000120
  Total: $0.000233
```

### Example 2: Code generation

**User message:** "Write a Python function to sort a list"
**Response:** ~200 tokens of code and explanation

```
**Token Usage** (GPT-4o, API):
  Input: 320 tokens
  Output: 215 tokens
  Total: 535 tokens

**Cost (USD):**
  Input: $0.000800
  Output: $0.002150
  Total: $0.002950
```

## Implementation Files

- `token_usage.py` - Core token counting and cost calculation logic
- `models.py` - Model definitions with pricing information
- `storage.py` - User preference storage (including token display setting)
- `bot.py` - Integration with Telegram bot handlers
