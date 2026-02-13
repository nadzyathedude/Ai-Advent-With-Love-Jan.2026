"""Configuration for the document indexing pipeline."""

import os
from dataclasses import dataclass, field


@dataclass
class ChunkingConfig:
    """Configuration for text chunking."""
    chunk_size: int = 800
    chunk_overlap: int = 150


@dataclass
class EmbeddingConfig:
    """Configuration for embedding generation."""
    model: str = "text-embedding-3-small"
    batch_size: int = 64
    max_retries: int = 3
    retry_delay: float = 1.0
    api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))


@dataclass
class IndexConfig:
    """Configuration for the document index."""
    schema_version: str = "1.0"
    output_path: str = "document_index.json"


@dataclass
class LLMConfig:
    """Configuration for LLM generation."""
    model: str = "gpt-4o-mini"
    temperature: float = 0.3
    max_tokens: int = 1024
    max_retries: int = 3
    retry_delay: float = 1.0
    api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))


@dataclass
class PipelineConfig:
    """Combined configuration for the entire pipeline."""
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    index: IndexConfig = field(default_factory=IndexConfig)
