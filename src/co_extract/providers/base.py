"""Base interfaces, data structures, and exceptions for extraction providers."""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from co_extract.ingest import Document
from co_extract.schema import ChangeOrder


class ProviderError(Exception):
    """Base exception for provider extraction failures."""


class ProviderAuthError(ProviderError):
    """Raised on missing, invalid, or unauthorized API keys."""


class ProviderRateLimitError(ProviderError):
    """Raised when provider rate limits are exhausted (HTTP 429)."""


class ProviderTimeoutError(ProviderError):
    """Raised when an API call times out."""


class ProviderBadOutputError(ProviderError):
    """Raised when a provider returns invalid, unparseable, or schema-violating output."""


class RawExtraction(BaseModel):
    """Result of an extraction by a single provider before validation and scoring."""

    change_order: ChangeOrder = Field(
        description="Parsed ChangeOrder model instance populated by the provider"
    )
    model_confidence: dict[str, float] = Field(
        default_factory=dict,
        description="Per-field self-reported confidence scores from the model",
    )
    input_tokens: int = Field(default=0, description="Number of prompt/input tokens consumed")
    output_tokens: int = Field(default=0, description="Number of completion/output tokens consumed")
    latency_ms: float = Field(default=0.0, description="Request execution latency in milliseconds")
    raw_response: Any = Field(default=None, description="Raw response payload from the provider")
    provider_name: str = Field(
        description="Name of the provider (e.g., 'claude', 'gemini', 'mock')"
    )
    model_name: str = Field(description="Underlying model identifier or fixture ID")


@runtime_checkable
class Extractor(Protocol):
    """Protocol implemented by all provider adapters."""

    name: str

    def extract(self, doc: Document) -> RawExtraction:
        """Extract a structured ChangeOrder from the given document."""
        ...
