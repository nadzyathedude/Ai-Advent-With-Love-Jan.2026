День 18. RAG — реранкинг, фильтрация по релевантности и сравнение качества

## Задача

Расширить RAG-пайплайн из дня 17, добавив:
1. Пороговую фильтрацию чанков по релевантности (threshold filter)
2. LLM-реранкинг — вторичную оценку релевантности через LLM
3. Стратегию фоллбэка при отсутствии релевантных чанков
4. Режим сравнения baseline vs enhanced для оценки улучшений

**Результат:** RAG с двухступенчатым контролем релевантности и CLI для A/B-сравнения.

---

## Архитектура

```
indexer/
├── __init__.py      # Экспорты пакета
├── settings.py      # Конфигурация + FallbackStrategy, RetrievalConfig
├── chunker.py       # Чанкинг текста с перекрытием
├── embeddings.py    # Провайдер эмбеддингов (OpenAI)
├── index.py         # Управление JSON-индексом
├── pipeline.py      # Оркестратор пайплайна индексации
├── retriever.py     # Поиск чанков + RetrievedChunk dataclass
├── llm.py           # Провайдер LLM (OpenAI Chat Completions)
├── reranker.py      # Reranker Protocol + LLMReranker
└── rag.py           # RAG-пайплайн: базовый + filtered с реранкингом

main.py              # CLI интерфейс (--threshold, --use-reranker, --compare)
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
# Базовый запрос (без фильтрации, как в дне 17)
python main.py ask document_index.json "О чём этот документ?"

# Больше контекста для ответа
python main.py ask document_index.json "Перечисли ключевые моменты" --top-k 10

# Другая модель для генерации
python main.py ask document_index.json "Что здесь важно?" --model gpt-4o
```

### Фильтрация по порогу релевантности

```bash
# Отсечь чанки с similarity < 0.75
python main.py ask index.json "What is an Activity?" --threshold 0.75

# Строгий порог (может сработать фоллбэк на лучший чанк)
python main.py ask index.json "What is an Activity?" --threshold 0.95
```

### LLM-реранкинг

```bash
# Реранкинг + фильтрация
python main.py ask index.json "What is an Activity?" --use-reranker --threshold 0.6
```

### Режим сравнения

```bash
# Сравнить baseline (без фильтрации) и enhanced (с порогом и/или реранкером)
python main.py ask index.json "What is an Activity?" --compare --threshold 0.7

# Сравнение с реранкером
python main.py ask index.json "What is an Activity?" --compare --threshold 0.7 --use-reranker
```

Вывод показывает статистику обоих прогонов и итоговое сравнение:
- Количество чанков до/после фильтрации
- Средний similarity и rerank score
- Наблюдения о том, что изменилось

### Программный API

```python
from indexer import (
    IndexingPipeline, answer_question, answer_question_filtered,
    RAGResult, LLMReranker, FallbackStrategy,
)
from indexer.llm import OpenAILLM

# Индексация
pipeline = IndexingPipeline()
pipeline.add_text("Ваш текст здесь", document_id="doc1")
pipeline.save("index.json")

# Базовый RAG (без фильтрации)
answer = answer_question(
    question="О чём этот документ?",
    index_path="index.json",
)

# Enhanced RAG с фильтрацией и реранкингом
llm = OpenAILLM()
reranker = LLMReranker(llm)

result: RAGResult = answer_question_filtered(
    question="О чём этот документ?",
    index_path="index.json",
    top_k=5,
    threshold=0.75,
    reranker=reranker,
    fallback_strategy=FallbackStrategy.TOP_1,
    llm_provider=llm,
)

print(result.answer)
print(f"Chunks: {result.chunks_retrieved} → {result.chunks_after_filter}")
print(f"Avg similarity: {result.avg_similarity:.3f}")
if result.avg_rerank_score is not None:
    print(f"Avg rerank: {result.avg_rerank_score:.3f}")
if result.used_fallback:
    print("Warning: fallback was used")
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
| `--threshold` | 0.75 | Порог релевантности (0.0–1.0) |
| `--use-reranker` | off | Включить LLM-реранкинг |
| `--compare` | off | Режим сравнения baseline vs enhanced |

---

## Как работает Enhanced RAG

```
Question → Embed → Cosine Top-K → [Rerank] → Threshold Filter → Prompt → LLM → Answer
                                      ↑              ↑
                                  optional      fallback strategy
```

1. **Embed** — вопрос преобразуется в эмбеддинг той же моделью, что при индексации
2. **Retrieve** — поиск top-k ближайших чанков по косинусному сходству
3. **Rerank** (опционально) — LLM оценивает каждый чанк по релевантности (0–1)
4. **Threshold Filter** — отсечение чанков ниже порога по `effective_score`
   - Если все отсечены: **TOP_1** фоллбэк (лучший чанк + предупреждение) или **INSUFFICIENT_CONTEXT** (пустой ответ)
5. **Augment** — чанки собираются в промпт с метаданными (similarity, rerank score)
6. **Generate** — LLM генерирует ответ на основе контекста

---

## Ключевые решения

- **Два dataclass сосуществуют**: `RetrievalResult` (базовый) и `RetrievedChunk` (обогащённый). Конвертер связывает их. Обратная совместимость полная.
- **Фоллбэк TOP_1** по умолчанию — полезнее, чем пустой ответ.
- **LLM реранкер скорит чанки поштучно** — надёжнее батч-скоринга: нет проблем с парсингом, graceful fallback на каждый чанк.
- **Режим сравнения** живёт в `main.py` — это presentation concern, не логика пайплайна.

---

## Особенности

- **Двухступенчатая фильтрация** — cosine similarity + LLM reranking
- **Graceful degradation** — при ошибке реранкера используется исходный similarity
- **A/B-сравнение из CLI** — `--compare` для быстрой оценки эффекта
- **RAG из коробки** — индексация + поиск + ответы в одном CLI
- **Детерминированные ID чанков** — стабильные хеши на основе контента
- **Косинусное сходство на чистом Python** — без зависимости от numpy
- **UTF-8 поддержка** — корректная работа с кириллицей и эмодзи
- **Батчинг** — эффективные API запросы для эмбеддингов
- **Retry с backoff** — устойчивость к временным ошибкам API
- **Расширяемость** — абстрактные `EmbeddingProvider`, `LLMProvider`, `Reranker` Protocol
- **Лимит контекста** — автоматическая обрезка контекста до ~12k символов

---

## Зависимости

- Python 3.10+
- openai >= 1.0.0
