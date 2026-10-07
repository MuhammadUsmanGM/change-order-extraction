"""Unit tests for the end-to-end extraction pipeline orchestrator."""

from decimal import Decimal
from pathlib import Path

from co_extract.pipeline import PipelineResult, run_pipeline
from co_extract.providers.base import RawExtraction
from co_extract.providers.mock import save_fixture
from co_extract.schema import ChangeOrder, ExtractedField


def test_run_pipeline_single_provider_mock(tmp_path: Path):
    """Verify run_pipeline executes single provider in mock mode."""
    raw_text = "Change Order CO-200 for Apex Tower. Total amount $8,500.00."
    from co_extract.ingest import ingest_document

    doc = ingest_document(raw_text)

    co = ChangeOrder(
        co_number=ExtractedField.from_value("CO-200", 0.95, "CO-200"),
        total_amount=ExtractedField.from_value(Decimal("8500.00"), 0.95, "$8,500.00"),
    )
    raw = RawExtraction(
        change_order=co,
        model_confidence={"co_number": 0.95, "total_amount": 0.95},
        provider_name="claude",
        model_name="claude-3-7-sonnet-20250219",
    )
    save_fixture(raw, doc.text, fixtures_dir=tmp_path)

    result = run_pipeline(
        source=raw_text,
        provider="claude",
        mock=True,
        fixtures_dir=tmp_path,
    )

    assert isinstance(result, PipelineResult)
    assert result.change_order.co_number.value == "CO-200"
    assert result.change_order.total_amount.value == Decimal("8500.00")
    assert result.providers_used == ["claude"]
    assert result.validation_report.is_valid is True
    assert result.change_order.co_number.confidence >= 0.85


def test_run_pipeline_dual_provider_both(tmp_path: Path):
    """Verify run_pipeline executes both providers and applies agreement in mock mode."""
    raw_text = "Change Order CO-300 for Sky Tower. Total amount $15,000.00."
    from co_extract.ingest import ingest_document

    doc = ingest_document(raw_text)

    co_claude = ChangeOrder(
        co_number=ExtractedField.from_value("CO-300", 0.95, "CO-300"),
        total_amount=ExtractedField.from_value(Decimal("15000.00"), 0.95, "$15,000.00"),
    )
    co_gemini = ChangeOrder(
        co_number=ExtractedField.from_value("co-300", 0.95, "CO-300"),
        total_amount=ExtractedField.from_value(Decimal("15000.00"), 0.95, "$15,000.00"),
    )

    raw_claude = RawExtraction(
        change_order=co_claude,
        provider_name="claude",
        model_name="claude-3-7-sonnet-20250219",
    )
    raw_gemini = RawExtraction(
        change_order=co_gemini,
        provider_name="gemini",
        model_name="gemini-2.5-flash",
    )

    save_fixture(raw_claude, doc.text, fixtures_dir=tmp_path)
    save_fixture(raw_gemini, doc.text, fixtures_dir=tmp_path)

    result = run_pipeline(
        source=raw_text,
        provider="both",
        mock=True,
        fixtures_dir=tmp_path,
    )

    assert result.providers_used == ["claude", "gemini"]
    # Both agreed: agreement signal is 1.0, score should be in AUTO_ACCEPT band
    assert result.change_order.co_number.confidence >= 0.90
