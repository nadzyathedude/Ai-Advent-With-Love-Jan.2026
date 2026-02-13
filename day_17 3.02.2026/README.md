День 17. RAG — поиск и ответы по документам

## Задача

Расширить пайплайн индексации из дня 16, добавив:
1. Поиск по индексу через косинусное сходство эмбеддингов
2. LLM-генерацию ответов на основе найденного контекста
3. Полный RAG-пайплайн: вопрос → эмбеддинг → поиск → промпт → ответ

**Результат:** CLI-инструмент для индексации документов и ответов на вопросы по ним.

---

## Архитектура

```
indexer/
├── __init__.py      # Экспорты пакета
├── settings.py      # Конфигурация (dataclasses)
├── chunker.py       # Чанкинг текста с перекрытием
├── embeddings.py    # Провайдер эмбеддингов (OpenAI)
├── index.py         # Управление JSON-индексом
├── pipeline.py      # Оркестратор пайплайна индексации
├── retriever.py     # Поиск чанков по косинусному сходству
├── llm.py           # Провайдер LLM (OpenAI Chat Completions)
└── rag.py           # RAG-пайплайн: retrieve → augment → generate

main.py              # CLI интерфейс
requirements.txt     # Зависимости
```

---

## Установка

```bash
# Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Установить зависимости
pip install -r requirements.txt

# Установить API ключ
export OPENAI_API_KEY="sk-..."
```

---

## Использование

### Индексация документов

```bash
# Индексировать один файл
python main.py file document.txt

# Индексировать несколько файлов
python main.py file doc1.txt doc2.txt doc3.txt

# Индексировать директорию (все .txt файлы)
python main.py dir ./documents

# Рекурсивно с паттерном
python main.py dir ./documents --pattern "*.md" --recursive

# Кастомные настройки
python main.py file doc.txt --chunk-size 1000 --overlap 200 --output my_index.json

# Текст из stdin
echo "Your text here" | python main.py text --doc-id my_doc
```

### RAG — ответы на вопросы

```bash
# Задать вопрос по индексу
python main.py ask document_index.json "О чём этот документ?"

# Больше контекста для ответа
python main.py ask document_index.json "Перечисли ключевые моменты" --top-k 10

# Другая модель для генерации
python main.py ask document_index.json "Что здесь важно?" --model gpt-4o
```

### Программный API

```python
from indexer import IndexingPipeline, PipelineConfig, ChunkingConfig
from indexer import answer_question

# Индексация
pipeline = IndexingPipeline()
pipeline.add_text("Ваш текст здесь", document_id="doc1")
pipeline.add_file("document.txt")
pipeline.save("index.json")

# RAG — ответ на вопрос
answer = answer_question(
    question="О чём этот документ?",
    index_path="index.json",
    top_k=5,
)
print(answer)
```

---

## Конфигурация

| Параметр | По умолчанию | Описание |
|----------|--------------|----------|
| `chunk_size` | 800 | Размер чанка в символах |
| `chunk_overlap` | 150 | Перекрытие между чанками |
| `model` (embedding) | text-embedding-3-small | Модель эмбеддингов OpenAI |
| `batch_size` | 64 | Размер батча для API запросов |
| `model` (LLM) | gpt-4o-mini | Модель для генерации ответов |
| `temperature` | 0.3 | Температура генерации |
| `max_tokens` | 1024 | Максимум токенов в ответе |
| `top_k` | 5 | Количество чанков для контекста |
| `output` | document_index.json | Путь к выходному файлу |

---

## Как работает RAG

1. **Embed** — вопрос пользователя преобразуется в эмбеддинг той же моделью, что использовалась при индексации
2. **Retrieve** — поиск top-k ближайших чанков по косинусному сходству (pure Python, без numpy)
3. **Augment** — найденные чанки собираются в промпт с метаданными (документ, score)
4. **Generate** — LLM генерирует ответ строго на основе предоставленного контекста

---

## Особенности

- **RAG из коробки** — индексация + поиск + ответы в одном CLI
- **Детерминированные ID чанков** — стабильные хеши на основе контента
- **Косинусное сходство на чистом Python** — без зависимости от numpy
- **UTF-8 поддержка** — корректная работа с кириллицей и эмодзи
- **Батчинг** — эффективные API запросы для эмбеддингов
- **Retry с backoff** — устойчивость к временным ошибкам API
- **Расширяемость** — абстрактные `EmbeddingProvider` и `LLMProvider`
- **Лимит контекста** — автоматическая обрезка контекста до ~12k символов

---

## Зависимости

- Python 3.10+
- openai >= 1.0.0
