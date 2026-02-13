# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Telegram bot powered by OpenAI's GPT-4o-mini model. The bot responds to user messages in Russian with AI-generated responses.

## Commands

```bash
# Install dependencies
pip install -r telegram_gpt_bot/requirements.txt

# Run the bot
python3 telegram_gpt_bot/bot.py
```

## Configuration

1. Copy the example config: `cp telegram_gpt_bot/config.example.py telegram_gpt_bot/config.py`
2. Fill in your API tokens in `config.py`:
   - `api_token_telegram` - Telegram Bot API token (from @BotFather)
   - `api_token_openai` - OpenAI API key

## Architecture

- **`telegram_gpt_bot/bot.py`** - Main bot application:
  - `/start` and `/help` command handlers
  - Message handler that sends user text to OpenAI and returns the response
  - Uses `python-telegram-bot` library with async handlers
  - System prompt defines bot personality and response formatting rules

- **`telegram_gpt_bot/config.py`** - API tokens (gitignored)

## Dependencies

- `python-telegram-bot` - Telegram Bot API wrapper
- `openai` - OpenAI API client
