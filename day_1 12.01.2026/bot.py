import logging
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

# Системный промпт для GPT
SYSTEM_PROMPT = """Ты — умный и дружелюбный ассистент в Telegram.

## Правила ответов:

### Для простых вопросов:
- Отвечай кратко и по существу
- Не растягивай ответ без необходимости

### Для сложных вопросов (математика, логика, программирование, анализ):
- Используй пошаговое рассуждение (Chain of Thought)
- Структура: 1) Анализ задачи → 2) Шаги решения → 3) Ответ/вывод

### Форматирование (Markdown для Telegram):
- **жирный** для важного
- `код` для терминов и коротких команд
- Блоки кода:
```язык
код здесь
```
- Списки через - или 1. 2. 3.

### Стиль:
- Дружелюбный, но профессиональный тон
- Если не знаешь ответ — честно скажи
- На русском, если пользователь пишет на русском"""


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

        # Отправляем ответ с Markdown
        await update.message.reply_text(
            assistant_message,
            parse_mode="Markdown"
        )

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
