# Repository Guidelines

## Project Structure & Module Organization
- `telegram_gpt_bot/` is the active Telegram bot implementation (see `bot.py`, `config.example.py`, `requirements.txt`).
- `telegram-gpt-bot/` holds historical Day 1/Day 2 snapshots; treat as archived reference.
- `day-4/` contains interview-task scripts (`run_interview.py`, `api_client.py`) plus a local `venv/`.
- Root files like `main.py` and `api_results.json` are standalone utilities or artifacts.

## Build, Test, and Development Commands
- Install bot dependencies: `pip install -r telegram_gpt_bot/requirements.txt`.
- Create local config: `cp telegram_gpt_bot/config.example.py telegram_gpt_bot/config.py`.
- Run the bot: `python3 telegram_gpt_bot/bot.py`.

## Coding Style & Naming Conventions
- Python 3 with 4-space indentation.
- Use `snake_case` for modules, functions, and variables; `CapWords` for classes.
- Keep secrets in `telegram_gpt_bot/config.py` (gitignored); do not hardcode tokens.
- No formatter/linter is configured—keep changes small and readable.

## Testing Guidelines
- No automated tests are present. Validate changes by running the bot locally and sending sample messages.
- If you add tests, place them under a new `tests/` folder and document how to run them.

## Commit & Pull Request Guidelines
- Commit messages in embedded repos are short, imperative, and sentence case (e.g., "Add README files for Day 1 and Day 2").
- PRs should describe the change, include config impacts (if any), and note how behavior was verified.

## Security & Configuration Tips
- Never commit API keys. Use `config.example.py` as the template and keep `config.py` local.
- Rotate tokens immediately if they are accidentally exposed.
