import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
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
from conversation_store import init_conversation_store, get_conversation_store
from summary_manager import SummaryManager

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация OpenAI клиента
client = OpenAI(api_key=api_token_openai)

# Summary manager (initialized after conversation store in main())
summary_manager: SummaryManager = None

# Callback data prefix for model selection
MODEL_CALLBACK_PREFIX = "select_model:"

# Conversation states for /summary setup flow
WAITING_FOR_THRESHOLD = 1

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
- Запоминать контекст диалога

**Команды:**
/start — начать сначала
/help — эта справка
/set\\_model — выбрать модель ИИ
/current\\_model — текущая модель
/tokens — управление отчётом о токенах
/summary — настройка сжатия диалога
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
/summary — Настроить автоматическое сжатие диалога
/summary\\_status — Статус сжатия диалога
/summary\\_off — Отключить сжатие
/summary\\_now — Принудительно сжать диалог сейчас
/clear\\_history — Очистить историю диалога
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


# =============================================================================
# Summary Commands
# =============================================================================

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик команды /summary - начинает настройку сжатия диалога.

    Returns:
        WAITING_FOR_THRESHOLD state to continue conversation
    """
    user = update.effective_user
    logger.info(f"User {user.id} started /summary setup")

    await update.message.reply_text(
        "**Настройка автоматического сжатия диалога**\n\n"
        "После какого количества сообщений сжимать диалог?\n"
        "Отправьте число от 1 до 500.\n\n"
        "_Рекомендуемое значение: 10-20 сообщений._\n\n"
        "Для отмены отправьте /cancel",
        parse_mode="Markdown"
    )
    return WAITING_FOR_THRESHOLD


async def summary_threshold_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработчик ввода порога сообщений для сжатия.

    Returns:
        ConversationHandler.END to finish conversation
    """
    user = update.effective_user
    text = update.message.text.strip()

    # Validate input
    try:
        threshold = int(text)
    except ValueError:
        await update.message.reply_text(
            "Пожалуйста, отправьте число от 1 до 500.\n"
            "Для отмены отправьте /cancel",
            parse_mode="Markdown"
        )
        return WAITING_FOR_THRESHOLD

    # Validate range
    if threshold < 1:
        await update.message.reply_text(
            "Число должно быть не меньше 1.\n"
            "Пожалуйста, отправьте число от 1 до 500.",
            parse_mode="Markdown"
        )
        return WAITING_FOR_THRESHOLD

    if threshold > 500:
        await update.message.reply_text(
            "Число должно быть не больше 500.\n"
            "Пожалуйста, отправьте число от 1 до 500.",
            parse_mode="Markdown"
        )
        return WAITING_FOR_THRESHOLD

    # Enable summarization with the threshold
    summary_manager.enable_summarization(user.id, threshold)

    await update.message.reply_text(
        f"Готово! Буду сжимать диалог каждые **{threshold}** сообщений.\n\n"
        "Сжатие помогает сохранять контекст разговора, "
        "уменьшая размер истории и стоимость.\n\n"
        "Команды управления:\n"
        "• `/summary_status` — текущий статус\n"
        "• `/summary_off` — отключить сжатие\n"
        "• `/summary_now` — сжать сейчас",
        parse_mode="Markdown"
    )

    logger.info(f"User {user.id} enabled summarization with threshold={threshold}")
    return ConversationHandler.END


async def summary_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена настройки сжатия."""
    await update.message.reply_text(
        "Настройка сжатия отменена.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def summary_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /summary_status - показывает статус сжатия."""
    user = update.effective_user
    status = summary_manager.get_status(user.id)

    if status["enabled"]:
        enabled_text = "включено"
        threshold_text = f"Порог: **{status['message_threshold']}** сообщений"
        count_text = f"Текущий счётчик: **{status['current_message_count']}**"
        until_text = f"До следующего сжатия: **{status['messages_until_next_summary']}** сообщений"
    else:
        enabled_text = "выключено"
        threshold_text = ""
        count_text = ""
        until_text = ""

    history_text = f"Сообщений в истории: **{status['total_messages_in_history']}**"
    summary_text = "есть" if status["has_summary"] else "нет"

    last_summary = status["last_summary_at"]
    if last_summary:
        last_summary_text = f"Последнее сжатие: {last_summary.strftime('%d.%m.%Y %H:%M')}"
    else:
        last_summary_text = "Сжатий ещё не было"

    lines = [
        f"**Статус сжатия диалога:** {enabled_text}",
        "",
    ]

    if status["enabled"]:
        lines.extend([threshold_text, count_text, until_text, ""])

    lines.extend([
        history_text,
        f"Накопленная сводка: {summary_text}",
        last_summary_text,
    ])

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    logger.info(f"User {user.id} checked summary status")


async def summary_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /summary_off - отключает сжатие."""
    user = update.effective_user
    summary_manager.disable_summarization(user.id)

    await update.message.reply_text(
        "Автоматическое сжатие диалога **отключено**.\n\n"
        "История диалога сохранена. "
        "Используйте /summary чтобы включить снова.",
        parse_mode="Markdown"
    )
    logger.info(f"User {user.id} disabled summarization")


async def summary_now_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /summary_now - принудительное сжатие."""
    user = update.effective_user

    status = summary_manager.get_status(user.id)
    if status["total_messages_in_history"] == 0:
        await update.message.reply_text(
            "Нечего сжимать — история диалога пуста.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        "Сжимаю диалог...",
        parse_mode="Markdown"
    )

    success = await summary_manager.force_summarize(user.id)

    if success:
        new_status = summary_manager.get_status(user.id)
        await update.message.reply_text(
            "Диалог успешно сжат!\n\n"
            f"Сообщений в истории: **{new_status['total_messages_in_history']}**\n"
            f"Счётчик сброшен: **{new_status['current_message_count']}**",
            parse_mode="Markdown"
        )
        logger.info(f"User {user.id} forced summarization successfully")
    else:
        await update.message.reply_text(
            "Не удалось сжать диалог. Попробуйте позже.\n"
            "История диалога сохранена.",
            parse_mode="Markdown"
        )
        logger.error(f"User {user.id} forced summarization failed")


async def clear_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /clear_history - очистка истории диалога."""
    user = update.effective_user
    store = get_conversation_store()
    store.clear_conversation(user.id)

    await update.message.reply_text(
        "История диалога очищена.\n"
        "Начинаем разговор с чистого листа!",
        parse_mode="Markdown"
    )
    logger.info(f"User {user.id} cleared conversation history")


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
        # Получаем хранилище разговоров и добавляем сообщение пользователя
        store = get_conversation_store()
        store.add_message(user.id, "user", user_message)

        # Получаем контекст разговора для OpenAI
        state = store.get_conversation_state(user.id)
        messages_for_api = state.get_context_for_openai(SYSTEM_PROMPT)

        # Полный текст запроса для подсчёта токенов
        full_input_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in messages_for_api
        )

        # Запрос к OpenAI API с контекстом разговора
        response = client.chat.completions.create(
            model=model_id,
            messages=messages_for_api,
            max_tokens=2000,
            temperature=0.7
        )

        assistant_message = response.choices[0].message.content
        logger.info(f"Ответ для {user.id} (модель {model_id}): {assistant_message[:50]}...")

        # Сохраняем ответ ассистента в историю
        store.add_message(user.id, "assistant", assistant_message)

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

        # Проверяем, нужно ли сжимать диалог (после ответа)
        if await summary_manager.summarize_if_needed(user.id):
            logger.info(f"Auto-summarization triggered for user {user.id}")

    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения (модель {model_id}): {e}")
        await update.message.reply_text(
            "Произошла ошибка при обработке запроса. "
            "Пожалуйста, попробуйте позже или переформулируйте вопрос."
        )


def main() -> None:
    """Запуск бота"""
    global summary_manager

    # Инициализируем базы данных
    init_database()
    init_conversation_store()

    # Инициализируем менеджер сводок
    summary_manager = SummaryManager(openai_client=client)

    # Создаём приложение
    application = Application.builder().token(api_token_telegram).build()

    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("set_model", set_model_command))
    application.add_handler(CommandHandler("current_model", current_model_command))
    application.add_handler(CommandHandler("tokens", tokens_command))
    application.add_handler(CommandHandler("show_commands", show_commands))

    # Обработчик настройки сжатия (ConversationHandler для интерактивного потока)
    summary_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("summary", summary_command)],
        states={
            WAITING_FOR_THRESHOLD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, summary_threshold_received)
            ],
        },
        fallbacks=[CommandHandler("cancel", summary_cancel)],
    )
    application.add_handler(summary_conv_handler)

    # Дополнительные команды для сжатия
    application.add_handler(CommandHandler("summary_status", summary_status_command))
    application.add_handler(CommandHandler("summary_off", summary_off_command))
    application.add_handler(CommandHandler("summary_now", summary_now_command))
    application.add_handler(CommandHandler("clear_history", clear_history_command))

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
