"""Unit tests for Claude and Gemini adapters with mocked SDK calls."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from co_extract.ingest import Document
from co_extract.providers.base import ProviderAuthError, ProviderBadOutputError
from co_extract.providers.claude import ClaudeExtractor
from co_extract.providers.gemini import GeminiExtractor
from co_extract.schema import ChangeOrder, ExtractedField


def test_claude_missing_api_key():
    """Verify ProviderAuthError is raised when Anthropic API key is absent."""
    extractor = ClaudeExtractor(api_key=None)
    with patch("co_extract.providers.claude.get_settings") as mock_settings:
        mock_settings.return_value.anthropic_api_key = None
        extractor.api_key = None
        doc = Document(text="CO text", pages=["CO text"])
        with pytest.raises(ProviderAuthError):
            extractor.extract(doc)


def test_gemini_missing_api_key():
    """Verify ProviderAuthError is raised when Gemini API key is absent."""
    extractor = GeminiExtractor(api_key=None)
    with patch("co_extract.providers.gemini.get_settings") as mock_settings:
        mock_settings.return_value.gemini_api_key = None
        extractor.api_key = None
        doc = Document(text="CO text", pages=["CO text"])
        with pytest.raises(ProviderAuthError):
            extractor.extract(doc)


def test_claude_successful_mocked_extraction():
    """Verify Claude adapter parses tool call response."""
    extractor = ClaudeExtractor(api_key="test-key")

    mock_client = MagicMock()
    mock_block = MagicMock()
    mock_block.type = "tool_use"
    mock_block.name = "extract_change_order"
    mock_block.input = {
        "co_number": {"value": "CO-88", "confidence": 0.95, "source_text": "CO-88"},
        "total_amount": {"value": "2400.00", "confidence": 0.99, "source_text": "$2,400.00"},
    }

    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50
    mock_client.messages.create.return_value = mock_response

    with patch.object(extractor, "_get_client", return_value=mock_client):
        doc = Document(text="Dummy change order CO-88 $2,400.00", pages=["Dummy change order"])
        res = extractor.extract(doc)

        assert res.change_order.co_number.value == "CO-88"
        assert res.change_order.total_amount.value == Decimal("2400.00")
        assert res.input_tokens == 100
        assert res.output_tokens == 50
        assert res.provider_name == "claude"


def test_gemini_successful_mocked_extraction():
    """Verify Gemini adapter parses structured JSON response."""
    extractor = GeminiExtractor(api_key="test-key")

    co = ChangeOrder(
        co_number=ExtractedField.from_value("CO-99"),
        total_amount=ExtractedField.from_value(Decimal("3500.50")),
    )
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = co.model_dump_json()
    mock_response.usage_metadata.prompt_token_count = 120
    mock_response.usage_metadata.candidates_token_count = 60
    mock_client.models.generate_content.return_value = mock_response

    with patch.object(extractor, "_get_client", return_value=mock_client):
        doc = Document(text="Dummy change order CO-99 $3,500.50", pages=["Dummy change order"])
        res = extractor.extract(doc)

        assert res.change_order.co_number.value == "CO-99"
        assert res.change_order.total_amount.value == Decimal("3500.50")
        assert res.input_tokens == 120
        assert res.output_tokens == 60
        assert res.provider_name == "gemini"


def test_gemini_empty_output_raises_error():
    """Verify Gemini returning empty text raises ProviderBadOutputError."""
    extractor = GeminiExtractor(api_key="test-key")
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = ""
    mock_client.models.generate_content.return_value = mock_response

    with patch.object(extractor, "_get_client", return_value=mock_client):
        doc = Document(text="Some text", pages=["Some text"])
        with pytest.raises(ProviderBadOutputError):
            extractor.extract(doc)
