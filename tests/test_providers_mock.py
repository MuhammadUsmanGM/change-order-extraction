"""Unit tests for the Mock provider and fixture recording/replay."""

from decimal import Decimal
from pathlib import Path

import pytest

from co_extract.ingest import Document
from co_extract.providers.base import ProviderBadOutputError, RawExtraction
from co_extract.providers.mock import (
    MockExtractor,
    compute_fixture_hash,
    load_fixture,
    save_fixture,
)
from co_extract.schema import ChangeOrder, ExtractedField


@pytest.fixture
def sample_raw_extraction() -> RawExtraction:
    """Fixture providing a sample RawExtraction."""
    co = ChangeOrder(
        co_number=ExtractedField.from_value("CO-101", 0.99, "Change Order # 101"),
        total_amount=ExtractedField.from_value(Decimal("15000.00"), 0.98, "$15,000.00"),
    )
    return RawExtraction(
        change_order=co,
        model_confidence={"co_number": 0.99, "total_amount": 0.98},
        input_tokens=150,
        output_tokens=75,
        latency_ms=120.0,
        raw_response={"status": "ok"},
        provider_name="claude",
        model_name="claude-3-7-sonnet-20250219",
    )


def test_compute_fixture_hash_deterministic():
    """Verify fixture hash is deterministic."""
    h1 = compute_fixture_hash("Sample doc text", "claude", "v1.0")
    h2 = compute_fixture_hash("Sample doc text", "claude", "v1.0")
    h3 = compute_fixture_hash("Different doc text", "claude", "v1.0")
    assert h1 == h2
    assert h1 != h3


def test_save_and_load_fixture(tmp_path: Path, sample_raw_extraction: RawExtraction):
    """Verify fixture save and load roundtrip."""
    doc_text = "This is a change order document for CO-101."
    saved_file = save_fixture(
        extraction=sample_raw_extraction,
        document_text=doc_text,
        fixtures_dir=tmp_path,
        prompt_version="v1.0",
    )
    assert saved_file.exists()

    loaded = load_fixture(
        document_text=doc_text,
        provider_name="claude",
        fixtures_dir=tmp_path,
        prompt_version="v1.0",
    )
    assert loaded.change_order.co_number.value == "CO-101"
    assert loaded.change_order.total_amount.value == Decimal("15000.00")
    assert loaded.input_tokens == 150
    assert loaded.output_tokens == 75
    assert loaded.provider_name == "claude"


def test_mock_extractor_replay(tmp_path: Path, sample_raw_extraction: RawExtraction):
    """Verify MockExtractor replays fixture from disk."""
    doc_text = "Change order text"
    save_fixture(
        extraction=sample_raw_extraction,
        document_text=doc_text,
        fixtures_dir=tmp_path,
    )

    doc = Document(text=doc_text, pages=[doc_text])
    extractor = MockExtractor(target_provider_name="claude", fixtures_dir=tmp_path)
    res = extractor.extract(doc)
    assert res.change_order.co_number.value == "CO-101"


def test_mock_extractor_missing_fixture(tmp_path: Path):
    """Verify missing fixture raises ProviderBadOutputError."""
    doc = Document(text="Unrecorded document", pages=["Unrecorded document"])
    extractor = MockExtractor(target_provider_name="claude", fixtures_dir=tmp_path)
    with pytest.raises(ProviderBadOutputError):
        extractor.extract(doc)


def test_mock_extractor_fallback(tmp_path: Path):
    """Verify MockExtractor with fallback data returns fallback on missing fixture."""
    co = ChangeOrder(co_number=ExtractedField.from_value("FALLBACK-1"))
    doc = Document(text="Missing fixture doc", pages=["Missing fixture doc"])
    extractor = MockExtractor(
        target_provider_name="claude",
        fixtures_dir=tmp_path,
        fallback_data=co,
    )
    res = extractor.extract(doc)
    assert res.change_order.co_number.value == "FALLBACK-1"
