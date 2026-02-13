import logging
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction
from openai import OpenAI

from config import api_token_telegram, api_token_openai

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Инициализация OpenAI клиента
client = OpenAI(api_key=api_token_openai)

# Системный промпт для GPT (JSON-only режим)
SYSTEM_PROMPT = """# System Prompt: JSON-Only Assistant (for Telegram Bot)

You are a programmatic agent inside a Telegram bot written in Python. Your task is to respond to user requests strictly in a machine-readable format.

## Core Rules (Mandatory)
1. **You MUST ALWAYS respond with valid JSON only** (a single JSON object) and nothing else.
2. **No plain text, markdown, explanations, code blocks, or quotes around the JSON.**
3. The response must be **strictly parseable** standard JSON (RFC 8259):
   - double quotes for strings
   - no trailing commas
   - no comments
4. If information is missing — **ask clarifying questions**, but still **ONLY in JSON**.
5. If the user requests something impossible/unclear/unsafe — return a refusal or error **ONLY in JSON**.

## Response Format (Unified)
Always return an object with the following keys:

- `status`: `"ok"` | `"need_clarification"` | `"error"`
- `language`: `"en"` (or `"ru"` if the user writes in Russian)
- `answer`: string with the main response (empty string allowed for errors)
- `data`: object with structured data (use `{}` if not applicable)
- `actions`: array of suggested actions/steps (use `[]` if not applicable)
- `clarifying_questions`: array of questions (required if status is `need_clarification`, otherwise `[]`)
- `error`: object (required if status is `error`, otherwise `{}`)

### Templates

#### Successful Response
{
  "status": "ok",
  "language": "en",
  "answer": "...",
  "data": {},
  "actions": [],
  "clarifying_questions": [],
  "error": {}
}

#### Clarification Needed
{
  "status": "need_clarification",
  "language": "en",
  "answer": "",
  "data": {},
  "actions": [],
  "clarifying_questions": ["Question 1", "Question 2"],
  "error": {}
}

#### Error / Refusal
{
  "status": "error",
  "language": "en",
  "answer": "",
  "data": {},
  "actions": [],
  "clarifying_questions": [],
  "error": {
    "code": "POLICY_OR_INVALID_REQUEST",
    "message": "Briefly explain the reason and suggest a safe alternative."
  }
}

## Additional Requirements
- If the user requests a list — duplicate it in `data` as an array and provide a short summary in `answer`.
- If the user requests instructions — populate `actions` with ordered steps.
- Any entities (links, dates, numbers, parameters) should be placed in `data` whenever possible.

## Self-Check Before Responding
Before returning the response:
- Ensure it is **a single JSON object**
- Ensure it is valid and parseable
- Ensure there are no extra characters before or after the JSON"""


def format_json_response(json_str: str) -> str:
    """Форматирует JSON-ответ GPT для отображения в Telegram"""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # Если не удалось распарсить — возвращаем как есть
        return json_str

    parts = []

    # Основной ответ
    if data.get("answer"):
        parts.append(data["answer"])

    # Уточняющие вопросы
    if data.get("clarifying_questions"):
        questions = data["clarifying_questions"]
        if questions:
            parts.append("\n❓ *Уточняющие вопросы:*")
            for q in questions:
                parts.append(f"• {q}")

    # Шаги/действия
    if data.get("actions"):
        actions = data["actions"]
        if actions:
            parts.append("\n📋 *Шаги:*")
            for i, action in enumerate(actions, 1):
                parts.append(f"{i}. {action}")

    # Ошибка
    if data.get("status") == "error" and data.get("error"):
        error = data["error"]
        error_msg = error.get("message", "Неизвестная ошибка")
        parts.append(f"⚠️ *Ошибка:* {error_msg}")

    return "\n".join(parts) if parts else json_str


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user = update.effective_user
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        "Я бот с искусственным интеллектом на базе GPT-4o-mini.\n"
        "Просто напиши мне сообщение, и я постараюсь помочь!\n\n"
        "Используй /help для справки."
    )
    logger.info(f"Пользователь {user.id} ({user.username}) запустил бота")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help"""
    help_text = """**Что я умею:**

- Отвечать на вопросы
- Помогать с кодом
- Объяснять сложные темы
- Решать задачи

**Команды:**
/start — начать сначала
/help — эта справка

Просто напиши сообщение! ✨"""
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений"""
    user = update.effective_user
    user_message = update.message.text

    logger.info(f"Сообщение от {user.id} ({user.username}): {user_message[:50]}...")

    # Показываем индикатор "печатает..."
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )

    try:
        # Запрос к OpenAI API
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            max_tokens=2000,
            temperature=0.7
        )

        assistant_message = response.choices[0].message.content
        logger.info(f"Ответ для {user.id}: {assistant_message[:50]}...")

        # Отправляем сырой JSON-ответ
        await update.message.reply_text(assistant_message)

    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")
        await update.message.reply_text(
            "Произошла ошибка при обработке запроса. "
            "Пожалуйста, попробуйте позже или переформулируйте вопрос."
        )


def main() -> None:
    """Запуск бота"""
    # Создаём приложение
    application = Application.builder().token(api_token_telegram).build()

    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запускаем бота
    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
