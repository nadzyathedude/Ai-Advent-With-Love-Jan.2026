import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatAction
from openai import OpenAI

from config import api_token_telegram, api_token_openai
from models import (
    SUPPORTED_MODELS,
    get_model_info,
    validate_and_get_model,
    format_model_list,
    get_default_model,
)
from storage import (
    init_database,
    get_user_model,
    set_user_model,
    get_user_show_tokens,
    set_user_show_tokens,
)
from token_usage import get_usage_report, format_usage_report

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация OpenAI клиента
client = OpenAI(api_key=api_token_openai)

# Callback data prefix for model selection
MODEL_CALLBACK_PREFIX = "select_model:"

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
        f"Привет, {user.first_name}!\n\n"
        "Я бот с искусственным интеллектом.\n"
        "Просто напиши мне сообщение, и я постараюсь помочь!\n\n"
        "Используй /help для справки."
    )
    await update.message.reply_text(
        "Чтобы увидеть все доступные команды, используй /show_commands"
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
/set\\_model — выбрать модель ИИ
/current\\_model — текущая модель
/tokens — управление отчётом о токенах
/show\\_commands — список всех команд

Просто напиши сообщение!"""
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def show_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /show_commands - показывает все доступные команды"""
    commands_text = """**Доступные команды:**

/start — Запустить бота, приветственное сообщение
/help — Справка о возможностях бота
/set\\_model — Выбрать модель ИИ для ответов
/current\\_model — Показать текущую выбранную модель
/tokens — Управление отчётом о токенах (on/off)
/show\\_commands — Показать этот список команд"""
    await update.message.reply_text(commands_text, parse_mode="Markdown")


async def set_model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /set_model - показывает клавиатуру выбора модели"""
    user = update.effective_user
    current_model = get_user_model(user.id)

    # Создаём инлайн-клавиатуру с моделями
    keyboard = []
    for model_id, model_info in SUPPORTED_MODELS.items():
        # Отмечаем текущую модель галочкой
        marker = " ✓" if model_id == current_model else ""
        button_text = f"{model_info.display_name}{marker}"
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"{MODEL_CALLBACK_PREFIX}{model_id}"
            )
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        format_model_list() + "\n\n**Выберите модель:**",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    logger.info(f"Пользователь {user.id} открыл меню выбора модели")


async def model_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик выбора модели через инлайн-кнопку"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    callback_data = query.data

    if not callback_data.startswith(MODEL_CALLBACK_PREFIX):
        return

    selected_model = callback_data[len(MODEL_CALLBACK_PREFIX):]

    # Валидируем выбранную модель
    valid_model, was_fallback = validate_and_get_model(selected_model)

    if was_fallback:
        await query.edit_message_text(
            f"Модель `{selected_model}` недоступна.\n"
            f"Установлена модель по умолчанию: `{valid_model}`",
            parse_mode="Markdown"
        )
        logger.warning(f"Пользователь {user.id} попытался выбрать недоступную модель: {selected_model}")
    else:
        model_info = get_model_info(valid_model)
        await query.edit_message_text(
            f"Модель успешно изменена!\n\n"
            f"**Выбрана:** `{valid_model}`\n"
            f"**Описание:** {model_info.description}",
            parse_mode="Markdown"
        )
        logger.info(f"Пользователь {user.id} выбрал модель: {valid_model}")

    # Сохраняем выбор пользователя
    set_user_model(user.id, valid_model)


async def current_model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /current_model - показывает текущую модель пользователя"""
    user = update.effective_user
    stored_model = get_user_model(user.id)

    # Валидируем сохранённую модель (на случай если она стала недоступна)
    valid_model, was_fallback = validate_and_get_model(stored_model)

    if was_fallback and stored_model is not None:
        # Модель стала недоступна, обновляем в базе
        set_user_model(user.id, valid_model)
        await update.message.reply_text(
            f"Ваша предыдущая модель `{stored_model}` больше недоступна.\n"
            f"Установлена модель по умолчанию: `{valid_model}`\n\n"
            "Используйте /set\\_model для выбора другой модели.",
            parse_mode="Markdown"
        )
    else:
        model_info = get_model_info(valid_model)
        is_default = stored_model is None
        status = " (по умолчанию)" if is_default else ""

        await update.message.reply_text(
            f"**Текущая модель:** `{valid_model}`{status}\n"
            f"**Описание:** {model_info.description}\n\n"
            "Используйте /set\\_model для выбора другой модели.",
            parse_mode="Markdown"
        )

    logger.info(f"Пользователь {user.id} проверил текущую модель: {valid_model}")


async def tokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /tokens - управление отображением информации о токенах"""
    user = update.effective_user
    args = context.args

    current_setting = get_user_show_tokens(user.id)

    if not args:
        # Показываем текущий статус
        status = "включён" if current_setting else "выключен"
        await update.message.reply_text(
            f"**Отчёт о токенах:** {status}\n\n"
            "Используйте:\n"
            "• `/tokens on` — включить отчёт\n"
            "• `/tokens off` — выключить отчёт",
            parse_mode="Markdown"
        )
        return

    arg = args[0].lower()

    if arg == "on":
        set_user_show_tokens(user.id, True)
        await update.message.reply_text(
            "Отчёт о токенах **включён**.\n"
            "После каждого ответа вы будете видеть информацию о токенах и стоимости.",
            parse_mode="Markdown"
        )
        logger.info(f"Пользователь {user.id} включил отчёт о токенах")
    elif arg == "off":
        set_user_show_tokens(user.id, False)
        await update.message.reply_text(
            "Отчёт о токенах **выключен**.\n"
            "Используйте `/tokens on` чтобы включить снова.",
            parse_mode="Markdown"
        )
        logger.info(f"Пользователь {user.id} выключил отчёт о токенах")
    else:
        await update.message.reply_text(
            "Неизвестный параметр. Используйте:\n"
            "• `/tokens on` — включить отчёт\n"
            "• `/tokens off` — выключить отчёт\n"
            "• `/tokens` — показать текущий статус",
            parse_mode="Markdown"
        )


def get_user_model_for_request(user_id: int) -> tuple[str, bool]:
    """
    Получить модель для запроса к OpenAI.

    Returns:
        tuple: (model_id, was_fallback)
    """
    stored_model = get_user_model(user_id)
    return validate_and_get_model(stored_model)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений"""
    user = update.effective_user
    user_message = update.message.text

    logger.info(f"Сообщение от {user.id} ({user.username}): {user_message[:50]}...")

    # Получаем модель пользователя
    model_id, was_fallback = get_user_model_for_request(user.id)

    # Если модель изменилась (была недоступна), уведомляем пользователя
    fallback_notice = ""
    if was_fallback:
        stored = get_user_model(user.id)
        if stored is not None:
            # Обновляем в базе на дефолтную
            set_user_model(user.id, model_id)
            fallback_notice = (
                f"_Ваша модель `{stored}` недоступна. "
                f"Использую `{model_id}`._\n\n"
            )

    # Показываем индикатор "печатает..."
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )

    try:
        # Полный текст запроса для подсчёта токенов (системный промпт + сообщение пользователя)
        full_input_text = SYSTEM_PROMPT + "\n" + user_message

        # Запрос к OpenAI API с выбранной моделью
        response = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            max_tokens=2000,
            temperature=0.7
        )

        assistant_message = response.choices[0].message.content
        logger.info(f"Ответ для {user.id} (модель {model_id}): {assistant_message[:50]}...")

        # Отправляем ответ с Markdown
        full_response = fallback_notice + assistant_message
        await update.message.reply_text(
            full_response,
            parse_mode="Markdown"
        )

        # Проверяем, нужно ли показывать отчёт о токенах
        if get_user_show_tokens(user.id):
            # Получаем отчёт об использовании токенов
            usage_report = get_usage_report(
                response=response,
                input_text=full_input_text,
                output_text=assistant_message,
                model_id=model_id
            )
            # Форматируем и отправляем отчёт как второе сообщение
            report_text = format_usage_report(usage_report)
            await update.message.reply_text(
                report_text,
                parse_mode="Markdown"
            )
            logger.info(
                f"Токены для {user.id}: input={usage_report.usage.input_tokens}, "
                f"output={usage_report.usage.output_tokens}, "
                f"cost=${usage_report.cost.total_cost:.6f}"
            )

    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения (модель {model_id}): {e}")
        await update.message.reply_text(
            "Произошла ошибка при обработке запроса. "
            "Пожалуйста, попробуйте позже или переформулируйте вопрос."
        )


def main() -> None:
    """Запуск бота"""
    # Инициализируем базу данных
    init_database()

    # Создаём приложение
    application = Application.builder().token(api_token_telegram).build()

    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("set_model", set_model_command))
    application.add_handler(CommandHandler("current_model", current_model_command))
    application.add_handler(CommandHandler("tokens", tokens_command))
    application.add_handler(CommandHandler("show_commands", show_commands))

    # Регистрируем обработчик callback-кнопок для выбора модели
    application.add_handler(
        CallbackQueryHandler(model_selection_callback, pattern=f"^{MODEL_CALLBACK_PREFIX}")
    )

    # Регистрируем обработчик сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запускаем бота
    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
