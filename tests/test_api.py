"""Integration tests for FastAPI application endpoints."""

from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from co_extract.api import app
from co_extract.providers.base import ProviderError, RawExtraction
from co_extract.providers.mock import DEFAULT_FIXTURES_DIR, save_fixture
from co_extract.schema import ChangeOrder, ExtractedField

client = TestClient(app)


def test_api_health_endpoint():
    """Verify /health returns healthy status without echoing sensitive keys."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert isinstance(data["claude_configured"], bool)
    assert isinstance(data["gemini_configured"], bool)
    # Ensure raw API keys are never exposed in the response
    assert "api_key" not in data


def test_api_providers_endpoint():
    """Verify /providers returns supported providers and configured model identifiers."""
    response = client.get("/providers")
    assert response.status_code == 200
    data = response.json()
    assert "claude" in data["available_providers"]
    assert "gemini" in data["available_providers"]
    assert "models" in data


def test_api_extract_json_mock():
    """Verify POST /extract with JSON body in mock mode."""
    raw_text = "API Test Change Order CO-777 Amount $3,000.00"
    from co_extract.ingest import ingest_document

    doc = ingest_document(raw_text)

    co = ChangeOrder(
        co_number=ExtractedField.from_value("CO-777", 0.95, "CO-777"),
        total_amount=ExtractedField.from_value(Decimal("3000.00"), 0.95, "$3,000.00"),
    )
    raw = RawExtraction(
        change_order=co,
        provider_name="claude",
        model_name="claude-mock",
    )
    save_fixture(raw, doc.text, fixtures_dir=DEFAULT_FIXTURES_DIR)

    payload = {
        "text": raw_text,
        "provider": "claude",
        "mock": True,
    }
    response = client.post("/extract", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "request_id" in data
    assert data["change_order"]["co_number"]["value"] == "CO-777"
    assert data["change_order"]["total_amount"]["value"] == "3000.00"


def test_api_extract_file_upload_mock():
    """Verify POST /extract with multipart file upload."""
    raw_text = "Uploaded File Change Order CO-888"
    from co_extract.ingest import ingest_document

    doc = ingest_document(raw_text)

    co = ChangeOrder(co_number=ExtractedField.from_value("CO-888", 0.95, "CO-888"))
    raw = RawExtraction(
        change_order=co,
        provider_name="claude",
        model_name="claude-mock",
    )
    save_fixture(raw, doc.text, fixtures_dir=DEFAULT_FIXTURES_DIR)

    files = {"file": ("order.txt", raw_text.encode("utf-8"), "text/plain")}
    data = {"provider": "claude", "mock": "true"}

    response = client.post("/extract", files=files, data=data)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["change_order"]["co_number"]["value"] == "CO-888"


def test_api_extract_empty_file_returns_400():
    """Verify empty file upload returns 400 Bad Request."""
    files = {"file": ("empty.txt", b"", "text/plain")}
    response = client.post("/extract", files=files)
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_api_extract_exceeding_max_upload_size():
    """Verify file upload exceeding MAX_UPLOAD_MB returns 413."""
    with patch("co_extract.api.get_settings") as mock_settings:
        mock_settings.return_value.max_upload_mb = 0  # 0 MB limit
        mock_settings.return_value.mock_mode = True

        files = {"file": ("big.txt", b"too big content", "text/plain")}
        response = client.post("/extract", files=files)
        assert response.status_code == 413


def test_api_extract_provider_error_returns_502():
    """Verify provider exception triggers 502 Bad Gateway response."""
    with patch("co_extract.api.run_pipeline") as mock_run:
        mock_run.side_effect = ProviderError("Provider failed to respond")
        payload = {"text": "dummy text", "provider": "claude", "mock": True}
        response = client.post("/extract", json=payload)
        assert response.status_code == 502
        assert "Provider failed to respond" in response.json()["detail"]
