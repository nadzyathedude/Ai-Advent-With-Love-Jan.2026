# 🔥 🔥 День 15. Environment 

Задача: Соединить агента с реальным окружением, заставить поднимать докер (как вариант эмулятор) и запускать в нем что-то  

Результат: Вы можете как итог своей работы что-то проверить на реальном девайсе
Email-уведомления через MCP

Добавить функционал отправки email-уведомлений при создании напоминания.

**Задача:**
- При создании напоминания бот спрашивает: "Хотите получить email-уведомление?"
- Если да — запрашивает email адрес
- При срабатывании напоминания отправляется email через Yandex Mail SMTP

**Результат:** Email-уведомления о задачах через MCP Tool `notification_send_email`

---

# Planner + MCP (Kubernetes-first)

24/7 AI-агент на Kubernetes с MCP-сервером, Task Tracker, напоминаниями, email-уведомлениями и фоновым планировщиком.

## Архитектура

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Kubernetes Cluster                               │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                      Namespace: ai-planner                          ││
│  │                                                                      ││
│  │  ┌─────────────────────┐         ┌─────────────────────────────┐   ││
│  │  │   MCP Server Pod    │         │     Telegram Bot Pod        │   ││
│  │  │   ┌─────────────┐   │  HTTP   │   ┌───────────────────┐     │   ││
│  │  │   │ mcp_server  │◀──┼─────────┼──▶│  bot.py           │     │   ││
│  │  │   │ .py         │   │ :8080   │   │  + MCP HTTP Client│     │   ││
│  │  │   └──────┬──────┘   │         │   │  + APScheduler    │     │   ││
│  │  │          │          │         │   └───────────────────┘     │   ││
│  │  │          ▼          │         │            │                │   ││
│  │  │   ┌──────────────┐  │         │            ▼                │   ││
│  │  │   │  tasks.db    │  │         │   ┌───────────────────┐     │   ││
│  │  │   │  (SQLite)    │  │         │   │ conversations.db  │     │   ││
│  │  │   └──────────────┘  │         │   │ memory.db         │     │   ││
│  │  │          │          │         │   └───────────────────┘     │   ││
│  │  │          │          │         │                              │   ││
│  │  │          ▼          │         │                              │   ││
│  │  │   ┌──────────────┐  │         │                              │   ││
│  │  │   │ Yandex SMTP  │──┼─────────┼──▶ Email Notifications      │   ││
│  │  │   └──────────────┘  │         │                              │   ││
│  │  └──────────┼──────────┘         └────────────┼────────────────┘   ││
│  │             │                                  │                    ││
│  │             ▼                                  ▼                    ││
│  │  ┌─────────────────────┐         ┌─────────────────────────────┐   ││
│  │  │  PVC: mcp-server-   │         │  PVC: bot-data              │   ││
│  │  │       data          │         │                             │   ││
│  │  └─────────────────────┘         └─────────────────────────────┘   ││
│  └──────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                              ┌───────────────┐
                              │   Telegram    │
                              │   Users       │
                              └───────────────┘
```

## Новые возможности (День 15)

- **Email уведомления**: отправка напоминаний на email через Yandex Mail SMTP
- **MCP Tool `notification_send_email`**: отправка email через MCP
- **Интерактивная настройка**: `/reminder_email` для управления email-уведомлениями
- **Кастомный формат email**:
  - Subject: название задачи
  - Body: "DO NOT FORGET - {название задачи}" + описание
- **Kubernetes-first**: полноценное развёртывание на K8s
- **MCP HTTP Server**: REST API вместо stdio для межподовой связи
- **Reminder Tool**: генерация сводок задач через MCP
- **APScheduler**: фоновый планировщик напоминаний
- **Yandex Calendar**: интеграция с CalDAV

## MCP Tools

| Инструмент | Описание |
|------------|----------|
| `task_create` | Создать задачу |
| `task_list_open` | Список открытых задач |
| `task_get_open_count` | Количество задач |
| `task_complete` | Завершить задачу |
| `reminder_generate_summary` | Сгенерировать сводку |
| `reminder_get_preferences` | Получить настройки |
| `reminder_set_preferences` | Установить настройки |
| `reminder_get_scheduled_users` | Пользователи по расписанию |
| `reminder_mark_sent` | Отметить отправку |
| `notification_send_email` | Отправить email уведомление |
| `notification_set_email_preferences` | Настроить email уведомления |
| `notification_get_email_preferences` | Получить настройки email |
| `notification_validate_email` | Валидация email адреса |

## Команды Telegram

### Напоминания
```
/reminder on          - Включить ежедневные напоминания
/reminder off         - Выключить напоминания
/reminder now         - Получить сводку сейчас
/reminder status      - Статус напоминаний (включая email)
/reminder set HH:MM   - Установить время (напр. 09:00)
/reminder_email       - Настроить email уведомления
```

### Задачи
```
/tasks               - Количество открытых задач
/task_add <title>    - Добавить задачу (интерактивный flow)
/task_add <title> | <description> - Добавить задачу с описанием
/task_list           - Список задач
/task_done <id>      - Завершить задачу + удалить из Yandex Calendar
```

### Процесс добавления задачи (`/task_add`)
```
/task_add Купить продукты | Молоко, хлеб, яйца
  → Задача создана: Купить продукты
  → Сгенерировать подзадачи? [Yes/No]
  → Установить напоминание? [1h/3h/Tomorrow/Custom/None]
  → Добавить в Yandex Calendar? [Yes/No]
  → Готово!

При срабатывании напоминания:
  → Telegram: ⏰ DO NOT FORGET - Купить продукты
              Молоко, хлеб, яйца
  → Email (если настроен):
      Subject: Купить продукты
      Body: DO NOT FORGET - Купить продукты
            Молоко, хлеб, яйца
```

## Yandex Mail (Email уведомления)

Интеграция с Яндекс Почтой для отправки напоминаний на email.

### Предварительные требования

**ВАЖНО:** Необходимо включить IMAP доступ в Яндекс Почте:

1. Откройте https://mail.yandex.ru/
2. Нажмите ⚙️ (настройки) → **Все настройки**
3. Перейдите в раздел **"Почтовые программы"**
4. Включите **"С сервера imap.yandex.ru по протоколу IMAP"**

### Настройка для локальной разработки

1. Создайте пароль приложения: https://id.yandex.ru/security/app-passwords
2. Выберите **«Почта»** и скопируйте пароль
3. Добавьте в `config.py`:
```python
yandex_smtp_email = "your-email@yandex.ru"
yandex_smtp_password = "your-app-password"  # НЕ основной пароль!
```

### Настройка для Kubernetes
```bash
# Закодируйте данные в base64
echo -n "your-email@yandex.ru" | base64
echo -n "your-app-password" | base64

# Отредактируйте k8s/secrets.yaml
# Заполните поля SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL
```

### Использование
```
Пользователь: /reminder_email

Бот: Email Notification Setup

Would you like to receive reminder notifications via email?
[Yes] [No]

Пользователь: [Yes]

Бот: Please enter your email address:

Пользователь: user@example.com

Бот: Email notifications enabled!
     Email: user@example.com
```

### Формат Email уведомлений

При создании задачи с описанием:
```
/task_add Позвонить врачу | Записаться на приём в 10:00
```

Email при напоминании:
```
Subject: Позвонить врачу

DO NOT FORGET - Позвонить врачу

Записаться на приём в 10:00
```

Telegram сообщение:
```
⏰ DO NOT FORGET - Позвонить врачу

Записаться на приём в 10:00
```

## Yandex Calendar

Интеграция с Яндекс Календарём через CalDAV.

### Настройка
1. Создайте пароль приложения: https://id.yandex.ru/security/app-passwords
2. Выберите «Календарь» и скопируйте пароль
3. Добавьте в `config.py`:
```python
yandex_calendar_username = "your-email@yandex.ru"
yandex_calendar_password = "your-app-password"  # НЕ основной пароль!
```

### Форматы даты/времени
- `today 14:30` — сегодня в 14:30
- `tomorrow 9:00` — завтра в 9:00
- `14:30` — сегодня (или завтра, если время прошло)
- `in 2 hours` — через 2 часа
- `2026-02-01 10:00` — конкретная дата

## Развёртывание на Kubernetes

### 1. Подготовка секретов

```bash
cd "day_15 30.01.2026"

# Закодируйте токены в base64
echo -n "your-telegram-bot-token" | base64
echo -n "your-openai-api-key" | base64
echo -n "your-yandex-smtp-email" | base64
echo -n "your-yandex-app-password" | base64

# Отредактируйте k8s/secrets.yaml с закодированными значениями
```

### 2. Сборка Docker-образов

```bash
# MCP Server
docker build -f Dockerfile.mcp-server -t ai-planner/mcp-server:latest .

# Telegram Bot
docker build -f Dockerfile.bot -t ai-planner/telegram-bot:latest .
```

### 3. Развёртывание

```bash
# Применить все ресурсы
kubectl apply -k k8s/

# Проверка
kubectl -n ai-planner get pods
kubectl -n ai-planner logs -f deployment/mcp-server
kubectl -n ai-planner logs -f deployment/telegram-bot
```

## Локальная разработка

### Вариант 1: Как сервис (рекомендуется)
```bash
# Запуск как фоновый сервис (переживает закрытие терминала)
./bot_service.sh start

# Управление сервисом
./bot_service.sh status   # Проверить статус
./bot_service.sh stop     # Остановить
./bot_service.sh restart  # Перезапустить
./bot_service.sh logs     # Смотреть логи в реальном времени
```

### Вариант 2: Прямой запуск
```bash
source venv/bin/activate
pip install -r requirements.txt

# Запуск бота (stdio режим, task_tracker_server запускается автоматически)
python bot.py
```

### Вариант 3: HTTP режим (как в K8s)
```bash
source venv/bin/activate

# Терминал 1: MCP Server
export DATA_DIR=./data
python mcp_server.py

# Терминал 2: Telegram Bot
export USE_HTTP_MCP=true
export MCP_SERVER_URL=http://localhost:8080
python bot.py
```

## Пример работы

### Создание задачи с напоминанием и email
```
Пользователь: /task_add Подготовить отчёт | Ежемесячный отчёт по продажам

Бот: Task created: Подготовить отчёт
     Ежемесячный отчёт по продажам

Бот: Would you like me to generate a to-do sublist?
     [Yes] [No]

Пользователь: [No]

Бот: When should I remind you about this task?
     [1h] [3h] [Tomorrow 9:00] [Custom] [No reminder]

Пользователь: [1h]

Бот: Reminder set for 2026-02-13 15:30!
```

### Напоминание через 1 час

**Telegram:**
```
⏰ DO NOT FORGET - Подготовить отчёт

Ежемесячный отчёт по продажам
```

**Email:**
```
From: nadzyathedude@yandex.ru
To: user@example.com
Subject: Подготовить отчёт

DO NOT FORGET - Подготовить отчёт

Ежемесячный отчёт по продажам
```

## Структура проекта

```
day_15 30.01.2026/
├── bot.py                   # Telegram бот + scheduler + email flow
├── bot_service.sh           # Скрипт управления сервисом
├── mcp_server.py            # MCP HTTP Server (K8s) + email tools
├── mcp_http_client.py       # MCP HTTP Client + email methods
├── scheduler.py             # APScheduler + email notifications
├── task_tracker_server.py   # MCP stdio server + email tools
├── task_tracker_client.py   # MCP stdio client
├── yandex_calendar.py       # Интеграция с Яндекс Календарём
├── config.py                # API токены и SMTP настройки
├── config.example.py        # Пример конфигурации
├── Dockerfile.mcp-server    # Docker для MCP Server
├── Dockerfile.bot           # Docker для бота
├── requirements.txt         # Python зависимости
├── k8s/                     # Kubernetes манифесты
│   ├── namespace.yaml
│   ├── secrets.yaml         # API токены + SMTP credentials
│   ├── configmap.yaml       # SMTP port, TLS settings
│   ├── pvc.yaml
│   ├── mcp-server.yaml
│   ├── telegram-bot.yaml
│   └── kustomization.yaml
└── README.md
```

## Надёжность

- **Автоматический перезапуск**: Kubernetes перезапускает упавшие поды
- **Health checks**: Liveness и Readiness probes
- **Retry logic**: HTTP Client и SMTP с exponential backoff (3 попытки)
- **Init container**: Бот ждёт готовности MCP Server
- **Persistent storage**: PVC для данных
- **Non-blocking email**: Ошибки email не блокируют Telegram уведомления

## Устранение неполадок

### SMTP Authentication Failed
```
Error: This user does not have access rights to this service
```

**Решение:**
1. Откройте https://mail.yandex.ru/ → Настройки → Почтовые программы
2. Включите "С сервера imap.yandex.ru по протоколу IMAP"
3. Создайте новый пароль приложения для "Почта"

### Email не отправляется
Проверьте логи:
```bash
tail -f bot.log | grep -i email
```

## Возможности предыдущих дней

- **День 14**: Yandex Calendar интеграция
- **День 13**: Планировщик + MCP
- **День 12**: Task Tracker MCP (stdio)
- **День 11**: Perplexity MCP интеграция
- **День 10**: Внешняя память (SQLite/JSON)
- **День 9**: Сжатие диалога
- **День 8**: Подсчёт токенов
- **День 7**: Выбор модели ИИ
