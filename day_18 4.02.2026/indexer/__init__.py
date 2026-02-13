"""Document Indexing Pipeline - Chunking + Embeddings + RAG"""

from .chunker import TextChunker, Chunk
from .embeddings import EmbeddingProvider, OpenAIEmbeddings
from .index import DocumentIndex, IndexedChunk, IndexedDocument
from .llm import LLMProvider, OpenAILLM
from .pipeline import IndexingPipeline
from .rag import answer_question, answer_question_filtered, RAGResult
from .reranker import Reranker, LLMReranker
from .retriever import Retriever, RetrievalResult, RetrievedChunk, cosine_similarity
from .settings import (
    PipelineConfig, ChunkingConfig, EmbeddingConfig, IndexConfig, LLMConfig,
    RetrievalConfig, FallbackStrategy,
)

__all__ = [
    "TextChunker",
    "Chunk",
    "EmbeddingProvider",
    "OpenAIEmbeddings",
    "DocumentIndex",
    "IndexedChunk",
    "IndexedDocument",
    "LLMProvider",
    "OpenAILLM",
    "IndexingPipeline",
    "answer_question",
    "answer_question_filtered",
    "RAGResult",
    "Reranker",
    "LLMReranker",
    "RetrievedChunk",
    "Retriever",
    "RetrievalResult",
    "cosine_similarity",
    "PipelineConfig",
    "ChunkingConfig",
    "EmbeddingConfig",
    "IndexConfig",
    "LLMConfig",
    "RetrievalConfig",
    "FallbackStrategy",
]
