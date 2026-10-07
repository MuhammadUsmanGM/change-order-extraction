"""Pipeline orchestrator unifying ingestion, extraction, validation, and scoring."""

import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from co_extract.confidence import ScoringSummary, calibrate_and_score_change_order
from co_extract.config import get_settings
from co_extract.ingest import Document, ingest_document
from co_extract.providers.base import Extractor, RawExtraction
from co_extract.providers.claude import ClaudeExtractor
from co_extract.providers.gemini import GeminiExtractor
from co_extract.providers.mock import DEFAULT_FIXTURES_DIR, MockExtractor, save_fixture
from co_extract.schema import ChangeOrder
from co_extract.validate import ValidationReport, validate_change_order


class PipelineResult(BaseModel):
    """Unified output of an end-to-end change-order extraction run."""

    change_order: ChangeOrder = Field(description="Validated and scored ChangeOrder model")
    document: Document = Field(description="Ingested document representation")
    validation_report: ValidationReport = Field(
        description="Deterministic validation report across V1-V10"
    )
    scoring_summary: ScoringSummary = Field(
        description="Confidence calibration summary and review band recommendation"
    )
    providers_used: list[str] = Field(description="List of provider adapters executed")
    latency_ms: float = Field(description="Total extraction pipeline latency in milliseconds")
    ocr_used: bool = Field(description="Whether OCR was performed during document ingestion")
    warnings: list[str] = Field(
        default_factory=list, description="Combined ingestion and extraction warnings"
    )


def _resolve_extractor(
    provider_name: str,
    mock: bool,
    fixtures_dir: Path | str,
) -> Extractor:
    """Instantiate appropriate extractor adapter based on provider and mock settings."""
    if mock:
        return MockExtractor(
            target_provider_name=provider_name,
            fixtures_dir=fixtures_dir,
        )

    if provider_name == "claude":
        return ClaudeExtractor()
    elif provider_name == "gemini":
        return GeminiExtractor()
    else:
        raise ValueError(f"Unknown provider '{provider_name}'. Supported: claude, gemini, both")


def run_pipeline(
    source: str | Path | bytes,
    filename: str | None = None,
    provider: Literal["claude", "gemini", "both"] = "claude",
    mock: bool | None = None,
    record: bool = False,
    fixtures_dir: Path | str = DEFAULT_FIXTURES_DIR,
) -> PipelineResult:
    """Execute the complete extraction, validation, and confidence scoring pipeline.

    Args:
        source: File path, raw document bytes, or plain text string.
        filename: Optional filename hint (e.g. for uploaded bytes).
        provider: Provider to execute ('claude', 'gemini', or 'both').
        mock: If True, uses pre-recorded offline fixtures. If None, reads MOCK_MODE env var.
        record: If True, saves live provider responses as offline fixtures.
        fixtures_dir: Directory where mock fixtures are stored/loaded.

    Returns:
        PipelineResult containing validated ChangeOrder, scores, and metadata.
    """
    settings = get_settings()
    is_mock = settings.mock_mode if mock is None else mock
    start_time = time.perf_counter()

    # 1. Ingest input into Document
    doc = ingest_document(source, filename=filename)

    # 2. Execute extraction(s)
    providers_used: list[str] = []
    comparison_co: ChangeOrder | None = None

    if provider == "both":
        extractor_claude = _resolve_extractor("claude", is_mock, fixtures_dir)
        extractor_gemini = _resolve_extractor("gemini", is_mock, fixtures_dir)

        raw_claude: RawExtraction = extractor_claude.extract(doc)
        raw_gemini: RawExtraction = extractor_gemini.extract(doc)

        if record and not is_mock:
            save_fixture(raw_claude, doc.text, fixtures_dir=fixtures_dir)
            save_fixture(raw_gemini, doc.text, fixtures_dir=fixtures_dir)

        primary_extraction = raw_claude
        comparison_co = raw_gemini.change_order
        providers_used = [raw_claude.provider_name, raw_gemini.provider_name]
    else:
        extractor = _resolve_extractor(provider, is_mock, fixtures_dir)
        primary_extraction = extractor.extract(doc)

        if record and not is_mock:
            save_fixture(primary_extraction, doc.text, fixtures_dir=fixtures_dir)

        providers_used = [primary_extraction.provider_name]

    # 3. Deterministic Validation (V1 - V10)
    co = primary_extraction.change_order
    val_report = validate_change_order(co, doc=doc)

    # 4. Multi-Signal Confidence Scoring & Agreement
    scoring_summary = calibrate_and_score_change_order(
        co=co,
        doc=doc,
        validation_report=val_report,
        comparison_co=comparison_co,
    )

    total_latency_ms = (time.perf_counter() - start_time) * 1000

    # 5. Assemble warnings
    combined_warnings = list(doc.warnings)
    if not val_report.is_valid:
        combined_warnings.append(
            f"Validation flagged {len(val_report.issues)} issue(s) across rules: {', '.join(val_report.failed_rules)}."
        )

    return PipelineResult(
        change_order=co,
        document=doc,
        validation_report=val_report,
        scoring_summary=scoring_summary,
        providers_used=providers_used,
        latency_ms=round(total_latency_ms, 2),
        ocr_used=doc.ocr_used,
        warnings=combined_warnings,
    )
