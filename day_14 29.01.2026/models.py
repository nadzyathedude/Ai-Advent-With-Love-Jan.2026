"""
OpenAI Model Management Module

Handles model definitions, validation, and selection logic.
Provides a clean interface for model-related operations.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelInfo:
    """Information about an OpenAI model."""
    id: str
    display_name: str
    description: str
    # Pricing per 1 million tokens (in USD)
    input_price_per_1m: float
    output_price_per_1m: float
    # tiktoken encoding name for fallback token counting
    tiktoken_encoding: str


# Supported models with their display information and pricing
# Pricing as of January 2025 (USD per 1M tokens)
SUPPORTED_MODELS: dict[str, ModelInfo] = {
    "gpt-4o": ModelInfo(
        id="gpt-4o",
        display_name="GPT-4o",
        description="Most capable model, best for complex tasks",
        input_price_per_1m=2.50,
        output_price_per_1m=10.00,
        tiktoken_encoding="o200k_base"
    ),
    "gpt-4.1": ModelInfo(
        id="gpt-4.1",
        display_name="GPT-4.1",
        description="Latest GPT-4 version with improvements",
        input_price_per_1m=2.00,
        output_price_per_1m=8.00,
        tiktoken_encoding="o200k_base"
    ),
    "gpt-4.1-mini": ModelInfo(
        id="gpt-4.1-mini",
        display_name="GPT-4.1 Mini",
        description="Faster and cheaper GPT-4.1 variant",
        input_price_per_1m=0.40,
        output_price_per_1m=1.60,
        tiktoken_encoding="o200k_base"
    ),
    "gpt-3.5-turbo": ModelInfo(
        id="gpt-3.5-turbo",
        display_name="GPT-3.5 Turbo",
        description="Fast and cost-effective for simple tasks",
        input_price_per_1m=0.50,
        output_price_per_1m=1.50,
        tiktoken_encoding="cl100k_base"
    ),
}

# Default model when user hasn't selected one
DEFAULT_MODEL = "gpt-4o"


def get_supported_model_ids() -> list[str]:
    """Return list of all supported model IDs."""
    return list(SUPPORTED_MODELS.keys())


def get_model_info(model_id: str) -> Optional[ModelInfo]:
    """Get model info by ID, returns None if not found."""
    return SUPPORTED_MODELS.get(model_id)


def is_valid_model(model_id: str) -> bool:
    """Check if model ID is valid and supported."""
    return model_id in SUPPORTED_MODELS


def get_default_model() -> str:
    """Return the default model ID."""
    return DEFAULT_MODEL


def validate_and_get_model(model_id: Optional[str]) -> tuple[str, bool]:
    """
    Validate model ID and return valid model.

    Returns:
        tuple: (model_id, was_fallback)
        - model_id: The validated model ID or default if invalid
        - was_fallback: True if fallback to default was needed
    """
    if model_id is None or not is_valid_model(model_id):
        return DEFAULT_MODEL, True
    return model_id, False


def format_model_list() -> str:
    """Format all supported models as a readable list."""
    lines = ["**Доступные модели:**\n"]
    for model_id, info in SUPPORTED_MODELS.items():
        default_marker = " (по умолчанию)" if model_id == DEFAULT_MODEL else ""
        lines.append(f"• `{model_id}` — {info.description}{default_marker}")
    return "\n".join(lines)
