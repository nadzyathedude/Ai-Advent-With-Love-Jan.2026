"""RAG pipeline: Question -> Embed -> Retrieve -> Augment -> LLM -> Answer."""

from pathlib import Path
from typing import List

from .embeddings import EmbeddingProvider, OpenAIEmbeddings
from .index import DocumentIndex
from .llm import LLMProvider, OpenAILLM
from .retriever import Retriever, RetrievalResult
from .settings import EmbeddingConfig, LLMConfig

# Default context char limit (~12k chars ≈ ~3k tokens, safe for most models)
DEFAULT_MAX_CONTEXT_CHARS = 12000


def _build_prompt(
    question: str,
    results: List[RetrievalResult],
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> str:
    """
    Build an augmented prompt from retrieved chunks and the user question.

    Args:
        question: The user's question
        results: Ranked retrieval results
        max_context_chars: Max total characters for context section

    Returns:
        Full prompt string ready for LLM
    """
    context_parts: list[str] = []
    total_chars = 0

    for i, result in enumerate(results, 1):
        chunk_text = result.chunk.text.strip()
        header = f"[Chunk {i} | doc: {result.document_id} | score: {result.score:.3f}]"
        section = f"{header}\n{chunk_text}"

        if total_chars + len(section) > max_context_chars:
            remaining = max_context_chars - total_chars
            if remaining > 100:
                context_parts.append(section[:remaining] + "...")
            break

        context_parts.append(section)
        total_chars += len(section)

    context = "\n\n".join(context_parts)

    return (
        "You are given the following context:\n\n"
        f"{context}\n\n"
        "Answer the question based only on the provided context. "
        "If the context does not contain enough information, say so.\n\n"
        f"Question:\n{question}"
    )


def answer_question(
    question: str,
    index_path: str,
    top_k: int = 5,
    embedding_provider: EmbeddingProvider | None = None,
    llm_provider: LLMProvider | None = None,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> str:
    """
    Full RAG pipeline: embed question -> retrieve -> augment -> generate answer.

    Args:
        question: User question text
        index_path: Path to the JSON index file
        top_k: Number of chunks to retrieve
        embedding_provider: Custom embedding provider (auto-configured if None)
        llm_provider: Custom LLM provider (auto-configured if None)
        max_context_chars: Max characters for context section

    Returns:
        LLM-generated answer string
    """
    # 1. Load index
    path = Path(index_path)
    if not path.exists():
        raise FileNotFoundError(f"Index file not found: {index_path}")

    index = DocumentIndex.load(index_path)

    if len(index) == 0:
        raise ValueError("Index is empty — no chunks to search")

    # 2. Create embedding provider matching the index model
    if embedding_provider is None:
        embedding_config = EmbeddingConfig(model=index.embedding_model)
        embedding_provider = OpenAIEmbeddings(embedding_config)

    # 3. Embed the question
    query_embedding = embedding_provider.embed_texts([question])[0]

    # 4. Validate dimension match
    sample_chunk = index.get_all_chunks()[0]
    if len(query_embedding) != len(sample_chunk.embedding):
        raise ValueError(
            f"Embedding dimension mismatch: query has {len(query_embedding)}, "
            f"index has {len(sample_chunk.embedding)}. "
            f"Ensure the same embedding model is used."
        )

    # 5. Retrieve top-k chunks
    retriever = Retriever(index)
    results = retriever.search(query_embedding, top_k=top_k)

    if not results:
        return "No relevant chunks found in the index."

    # 6. Build augmented prompt
    prompt = _build_prompt(question, results, max_context_chars)

    # 7. Call LLM
    if llm_provider is None:
        llm_provider = OpenAILLM()

    return llm_provider.generate(prompt)
