"""
Token Usage and Cost Calculation Module

Provides token counting (from API response or fallback tiktoken estimation)
and cost calculation based on model pricing.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import tiktoken

from models import get_model_info, ModelInfo

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Container for token usage information."""
    input_tokens: int
    output_tokens: int
    total_tokens: int
    # Whether usage was from API (True) or estimated locally (False)
    from_api: bool


@dataclass
class UsageCost:
    """Container for cost calculation results."""
    input_cost: float
    output_cost: float
    total_cost: float
    # True if pricing was found for the model
    pricing_available: bool


@dataclass
class UsageReport:
    """Combined usage and cost report."""
    usage: TokenUsage
    cost: UsageCost
    model_id: str


def extract_usage_from_response(response) -> Optional[TokenUsage]:
    """
    Extract token usage from OpenAI API response.

    Args:
        response: OpenAI ChatCompletion response object

    Returns:
        TokenUsage if usage data is available, None otherwise
    """
    try:
        if response.usage is None:
            return None

        usage = response.usage
        return TokenUsage(
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            from_api=True
        )
    except AttributeError as e:
        logger.warning(f"Could not extract usage from API response: {e}")
        return None


def count_tokens_locally(
    text: str,
    encoding_name: str = "cl100k_base"
) -> int:
    """
    Count tokens in text using tiktoken.

    Args:
        text: Text to count tokens for
        encoding_name: tiktoken encoding name

    Returns:
        Token count
    """
    try:
        encoding = tiktoken.get_encoding(encoding_name)
        return len(encoding.encode(text))
    except Exception as e:
        logger.error(f"Error counting tokens with tiktoken: {e}")
        # Rough estimation as last resort: ~4 characters per token
        return len(text) // 4


def estimate_usage_locally(
    input_text: str,
    output_text: str,
    model_id: str
) -> TokenUsage:
    """
    Estimate token usage locally using tiktoken.

    Args:
        input_text: The input/prompt text
        output_text: The output/completion text
        model_id: Model ID to determine encoding

    Returns:
        TokenUsage with estimated counts
    """
    model_info = get_model_info(model_id)
    encoding_name = model_info.tiktoken_encoding if model_info else "cl100k_base"

    input_tokens = count_tokens_locally(input_text, encoding_name)
    output_tokens = count_tokens_locally(output_text, encoding_name)

    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        from_api=False
    )


def calculate_cost(usage: TokenUsage, model_id: str) -> UsageCost:
    """
    Calculate cost based on token usage and model pricing.

    Args:
        usage: Token usage data
        model_id: Model ID to look up pricing

    Returns:
        UsageCost with calculated costs
    """
    model_info = get_model_info(model_id)

    if model_info is None:
        logger.warning(f"No pricing info for model {model_id}, costs set to 0")
        return UsageCost(
            input_cost=0.0,
            output_cost=0.0,
            total_cost=0.0,
            pricing_available=False
        )

    # Cost formula: (tokens / 1_000_000) * price_per_1M
    input_cost = (usage.input_tokens / 1_000_000) * model_info.input_price_per_1m
    output_cost = (usage.output_tokens / 1_000_000) * model_info.output_price_per_1m
    total_cost = input_cost + output_cost

    return UsageCost(
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=total_cost,
        pricing_available=True
    )


def get_usage_report(
    response,
    input_text: str,
    output_text: str,
    model_id: str
) -> UsageReport:
    """
    Get complete usage report with tokens and costs.

    Prefers API usage data when available, falls back to local estimation.

    Args:
        response: OpenAI API response (may be None for fallback)
        input_text: Input text for fallback estimation
        output_text: Output text for fallback estimation
        model_id: Model ID for pricing and encoding lookup

    Returns:
        UsageReport with usage and cost data
    """
    # Try to get usage from API response first
    usage = None
    if response is not None:
        usage = extract_usage_from_response(response)

    # Fall back to local estimation if API usage not available
    if usage is None:
        usage = estimate_usage_locally(input_text, output_text, model_id)
        logger.info(f"Using local token estimation for model {model_id}")

    # Calculate cost
    cost = calculate_cost(usage, model_id)

    return UsageReport(
        usage=usage,
        cost=cost,
        model_id=model_id
    )


def format_usage_report(report: UsageReport) -> str:
    """
    Format usage report as a Telegram message.

    Args:
        report: UsageReport to format

    Returns:
        Formatted string for Telegram
    """
    model_info = get_model_info(report.model_id)
    model_name = model_info.display_name if model_info else report.model_id

    # Token source indicator
    source = "API" if report.usage.from_api else "estimate"

    # Cost display
    if report.cost.pricing_available:
        cost_input = f"${report.cost.input_cost:.6f}"
        cost_output = f"${report.cost.output_cost:.6f}"
        cost_total = f"${report.cost.total_cost:.6f}"
    else:
        cost_input = "N/A (price unknown)"
        cost_output = "N/A (price unknown)"
        cost_total = "N/A (price unknown)"

    lines = [
        f"**Token Usage** ({model_name}, {source}):",
        f"  Input: {report.usage.input_tokens:,} tokens",
        f"  Output: {report.usage.output_tokens:,} tokens",
        f"  Total: {report.usage.total_tokens:,} tokens",
        "",
        "**Cost (USD):**",
        f"  Input: {cost_input}",
        f"  Output: {cost_output}",
        f"  Total: {cost_total}",
    ]

    return "\n".join(lines)
