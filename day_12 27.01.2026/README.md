# День 12. Task Tracker MCP

Создайте собственный MCP-сервер с инструментом "Task Tracker" и подключите к нему Telegram-бота.

## Задание

1. Реализовать MCP-сервер с инструментами для управления задачами
2. Подключить Telegram-бота к MCP-серверу
3. Бот вызывает инструменты через MCP (JSON-RPC), а не импортируя код напрямую

## Результат

Telegram-бот с собственным MCP-сервером для отслеживания задач:
- Создание, просмотр и завершение задач
- Персистентное хранение в SQLite
- Полноценная MCP-интеграция через stdio транспорт

## Новые возможности (День 12)

- **Task Tracker MCP Server**: собственный MCP-сервер на Python
- **4 MCP-инструмента**: создание, список, подсчёт, завершение задач
- **SQLite хранилище**: задачи сохраняются между перезапусками
- **Команды бота**: `/tasks`, `/task_add`, `/task_list`, `/task_done`

### Task Tracker MCP Tools

| Инструмент | Описание |
|------------|----------|
| `task_create` | Создать новую задачу |
| `task_list_open` | Список открытых задач пользователя |
| `task_get_open_count` | Количество открытых задач |
| `task_complete` | Отметить задачу как выполненную |

### Архитектура

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

### Пример использования

```
Пользователь: /task_add Изучить MCP протокол
Бот: Task created!
     ID: 1
     Title: Изучить MCP протокол

Пользователь: /task_add Написать документацию | Обновить README
Бот: Task created!
     ID: 2
     Title: Написать документацию
     Description: Обновить README

Пользователь: /tasks
Бот: Open tasks: 2

Пользователь: /task_list
Бот: Open Tasks (2):
     1. Изучить MCP протокол
     2. Написать документацию
        Обновить README

Пользователь: /task_done 1
Бот: Task 1 marked as completed!

Пользователь: /tasks
Бот: Open tasks: 1
```

## Возможности (День 11)

- **MCP интеграция**: подключение к Perplexity MCP Server
- **Команда `/mcp_tools`**: просмотр доступных MCP-инструментов
- **Кэширование**: результаты кэшируются на 30 секунд

### Perplexity MCP Server

| Инструмент | Описание |
|------------|----------|
| `perplexity_search` | Поиск в интернете через Perplexity Search API |
| `perplexity_chat` | Разговорный ИИ с веб-поиском (sonar-pro) |
| `perplexity_research` | Глубокие исследования с цитатами (sonar-deep-research) |
| `perplexity_reason` | Продвинутые рассуждения (sonar-reasoning-pro) |

## Возможности (День 10)

- **Выбор формата хранения**: SQLite (рекомендуется) или JSON
- **Архивирование вместо удаления**: старые сообщения помечаются как неактивные
- **Многоуровневое сжатие**: мета-саммари для накопленных сводок
- **Поиск в памяти**: релевантная информация из архива

## Возможности (День 9)

- `/summary` — настройка внешней памяти и сжатия диалога
- `/summary_status` — статус внешней памяти
- Автоматическое сжатие после N сообщений

## Возможности (День 8)

- `/tokens` — управление отчётом о токенах (on/off)
- Расчёт стоимости в USD

## Возможности (День 7)

- `/set_model` — выбор модели ИИ
- `/current_model` — текущая модель

## Структура проекта

```
day_12 27.01.2026/
├── bot.py                  # Основной файл бота
├── task_tracker_server.py  # MCP-сервер Task Tracker
├── task_tracker_client.py  # MCP-клиент для Task Tracker
├── mcp_client.py           # MCP-клиент для Perplexity
├── models.py               # Управление моделями
├── storage.py              # Хранение настроек пользователей
├── token_usage.py          # Подсчёт токенов
├── conversation_store.py   # История диалогов
├── external_memory.py      # Внешняя память
├── memory_retrieval.py     # Поиск и сборка контекста
├── summary_manager.py      # Логика сжатия диалога
├── config.py               # API-токены (не в git)
├── requirements.txt        # Зависимости
├── tasks.db                # БД задач (создаётся автоматически)
├── TASK_TRACKER_MCP.md     # Документация Task Tracker
├── EXTERNAL_MEMORY.md      # Документация внешней памяти
├── TOKEN_COUNTING.md       # Документация по токенам
└── README.md               # Этот файл
```

## Запуск

```bash
# Активация виртуального окружения
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt

# Настройка токенов
cp config.example.py config.py
# Заполните токены в config.py

# Запуск бота
python bot.py
```

## Команды бота

### Task Tracker (MCP)

| Команда | Описание |
|---------|----------|
| `/tasks` | Количество открытых задач |
| `/task_add <title>` | Создать задачу |
| `/task_add <title> \| <desc>` | Создать задачу с описанием |
| `/task_list` | Список открытых задач |
| `/task_done <id>` | Завершить задачу |
| `/task_tools` | Показать MCP-инструменты Task Tracker |

### Основные

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие |
| `/help` | Справка |
| `/set_model` | Выбор модели ИИ |
| `/current_model` | Текущая модель |
| `/tokens` | Статус отчёта о токенах |
| `/mcp_tools` | MCP-инструменты Perplexity |
| `/show_commands` | Список всех команд |

### Внешняя память

| Команда | Описание |
|---------|----------|
| `/summary` | Настроить внешнюю память |
| `/summary_status` | Статус |
| `/summary_on` | Включить |
| `/summary_off` | Отключить |
| `/summary_now` | Сжать сейчас |
| `/clear_history` | Очистить историю |

## MCP (Model Context Protocol)

### Что такое MCP?

Model Context Protocol — открытый стандарт для подключения ИИ-ассистентов к внешним источникам данных и инструментам. Протокол использует JSON-RPC 2.0.

### Транспорт

Используется **stdio** транспорт — бот запускает MCP-сервер как подпроцесс и общается через stdin/stdout.

### Формат сообщений

**Запрос (tools/list):**
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list"
}
```

**Запрос (tools/call):**
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

**Ответ:**
```json
{
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
        "content": [{"type": "text", "text": "{\"count\": 5}"}]
    }
}
```

## Документация

- [TASK_TRACKER_MCP.md](TASK_TRACKER_MCP.md) — Task Tracker MCP (День 12)
- [EXTERNAL_MEMORY.md](EXTERNAL_MEMORY.md) — внешняя память
- [TOKEN_COUNTING.md](TOKEN_COUNTING.md) — учёт токенов
- [DIALOG_SUMMARY.md](DIALOG_SUMMARY.md) — сжатие диалога
