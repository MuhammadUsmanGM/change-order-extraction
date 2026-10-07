"""Confidence scoring, multi-signal weighting, and cross-provider agreement."""

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from co_extract.ingest import Document
from co_extract.schema import ChangeOrder, ExtractedField
from co_extract.validate import ValidationReport, check_grounding_match

# Default weights (tuned on eval)
DEFAULT_W1_MODEL = 0.30
DEFAULT_W2_GROUNDING = 0.25
DEFAULT_W3_VALIDATION = 0.25
DEFAULT_W4_AGREEMENT = 0.20

# Hard override caps
CAP_UNGROUNDED = 0.30
CAP_DISAGREEMENT = 0.50

# Decision band thresholds
THRESH_AUTO_ACCEPT = 0.85
THRESH_NEEDS_REVIEW = 0.60


class ReviewBand(StrEnum):
    """Categorization for automated review workflow."""

    AUTO_ACCEPT = "auto_accept"
    NEEDS_REVIEW = "needs_review"
    REJECT = "reject"


class ConfidenceBreakdown(BaseModel):
    """Signal decomposition for a single field's confidence score."""

    model_conf: float
    grounding: float
    validation: float
    agreement: float
    raw_score: float
    final_score: float
    capped_reason: str | None = None
    review_band: ReviewBand


def _normalize_value_for_comparison(val: Any) -> Any:
    """Normalize values to allow robust equality comparisons across providers."""
    if val is None:
        return None
    if isinstance(val, Decimal):
        # Round to 2 decimal places
        return round(val, 2)
    if isinstance(val, (date, int, bool)):
        return val
    if isinstance(val, str):
        # Lowercase and normalize whitespace
        cleaned = re.sub(r"\s+", " ", val.strip().lower())
        return cleaned
    return str(val)


def check_values_agree(val1: Any, val2: Any) -> bool:
    """Check if two values from different providers agree after normalization."""
    norm1 = _normalize_value_for_comparison(val1)
    norm2 = _normalize_value_for_comparison(val2)

    if norm1 is None and norm2 is None:
        return True
    if norm1 is None or norm2 is None:
        return False

    if isinstance(norm1, Decimal) and isinstance(norm2, Decimal):
        return abs(norm1 - norm2) <= Decimal("0.01")

    return norm1 == norm2


def compute_field_confidence(
    model_conf: float,
    grounding_score: float,
    has_validation_flag: bool,
    agreement_score: float,  # 1.0 (agree), 0.0 (disagree), 0.5 (single provider)
    is_value_present: bool,
    w1: float = DEFAULT_W1_MODEL,
    w2: float = DEFAULT_W2_GROUNDING,
    w3: float = DEFAULT_W3_VALIDATION,
    w4: float = DEFAULT_W4_AGREEMENT,
) -> ConfidenceBreakdown:
    """Calculate the calibrated confidence score using weighted multi-signal scoring."""
    # 1. Model self-reported score
    m_score = max(0.0, min(1.0, model_conf))

    # 2. Grounding score
    g_score = max(0.0, min(1.0, grounding_score))

    # 3. Validation score: 1.0 if clean, 0.0 if failed
    v_score = 0.0 if has_validation_flag else 1.0

    # 4. Agreement score
    a_score = max(0.0, min(1.0, agreement_score))

    # Raw weighted sum
    raw_score = (w1 * m_score) + (w2 * g_score) + (w3 * v_score) + (w4 * a_score)
    final_score = max(0.0, min(1.0, raw_score))
    capped_reason: str | None = None

    # Apply hard overrides only when a value is actually extracted
    if is_value_present:
        # Override 1: Ungrounded value cap
        if g_score < 0.5:
            if final_score > CAP_UNGROUNDED:
                final_score = CAP_UNGROUNDED
                capped_reason = "ungrounded_value"

        # Override 2: Cross-provider disagreement cap
        if agreement_score == 0.0:
            if final_score > CAP_DISAGREEMENT:
                final_score = CAP_DISAGREEMENT
                capped_reason = capped_reason or "providers_disagree"

    # Determine Review Band
    if final_score >= THRESH_AUTO_ACCEPT:
        band = ReviewBand.AUTO_ACCEPT
    elif final_score >= THRESH_NEEDS_REVIEW:
        band = ReviewBand.NEEDS_REVIEW
    else:
        band = ReviewBand.REJECT

    return ConfidenceBreakdown(
        model_conf=m_score,
        grounding=g_score,
        validation=v_score,
        agreement=a_score,
        raw_score=round(raw_score, 4),
        final_score=round(final_score, 4),
        capped_reason=capped_reason,
        review_band=band,
    )


class ScoringSummary(BaseModel):
    """Aggregate confidence summary for an extraction."""

    mean_confidence: float = Field(description="Average confidence across non-null fields")
    min_confidence: float = Field(description="Minimum confidence across non-null fields")
    review_band: ReviewBand = Field(description="Overall document review recommendation")
    field_breakdowns: dict[str, ConfidenceBreakdown] = Field(
        default_factory=dict, description="Detailed breakdown per field"
    )


def calibrate_and_score_change_order(
    co: ChangeOrder,
    doc: Document | None = None,
    validation_report: ValidationReport | None = None,
    comparison_co: ChangeOrder | None = None,
) -> ScoringSummary:
    """Calibrate and update confidence scores in-place on a ChangeOrder model.

    Args:
        co: The primary ChangeOrder being scored.
        doc: The ingested Document (for grounding checks).
        validation_report: Validation results containing detected flags.
        comparison_co: Secondary ChangeOrder from another provider for cross-provider agreement.
    """
    flagged_fields = set()
    if validation_report:
        for issue in validation_report.issues:
            flagged_fields.add(issue.field_path)

    breakdowns: dict[str, ConfidenceBreakdown] = {}
    doc_text = doc.text if doc else ""

    # Fields to evaluate on the root model
    scalar_fields = [
        "co_number",
        "revision",
        "date_issued",
        "project_name",
        "project_number",
        "owner",
        "contractor",
        "subcontractor",
        "reason",
        "description",
        "total_amount",
        "currency",
        "direction",
        "original_contract_sum",
        "revised_contract_sum",
        "schedule_impact_days",
        "new_completion_date",
        "status",
    ]

    for fname in scalar_fields:
        fld: ExtractedField[Any] = getattr(co, fname)
        is_present = fld.value is not None

        # 1. Grounding signal
        if is_present and doc_text:
            g_score, _ = check_grounding_match(fld.source_text, doc_text)
        else:
            g_score = 1.0  # neutral if absent or no doc

        # 2. Validation signal
        has_flag = fname in flagged_fields or len(fld.flags) > 0

        # 3. Agreement signal
        if comparison_co is not None:
            comp_fld: ExtractedField[Any] = getattr(comparison_co, fname)
            agrees = check_values_agree(fld.value, comp_fld.value)
            a_score = 1.0 if agrees else 0.0
            if not agrees and is_present:
                if "providers_disagree" not in fld.flags:
                    fld.flags.append("providers_disagree")
        else:
            a_score = 0.5  # neutral single-provider

        # Compute breakdown
        bd = compute_field_confidence(
            model_conf=fld.confidence,
            grounding_score=g_score,
            has_validation_flag=has_flag,
            agreement_score=a_score,
            is_value_present=is_present,
        )
        fld.confidence = bd.final_score
        breakdowns[fname] = bd

    # Compute overall aggregates
    non_null_confidences = [
        bd.final_score for fname, bd in breakdowns.items() if getattr(co, fname).value is not None
    ]

    if non_null_confidences:
        mean_conf = sum(non_null_confidences) / len(non_null_confidences)
        min_conf = min(non_null_confidences)
    else:
        mean_conf = 1.0
        min_conf = 1.0

    if min_conf < THRESH_NEEDS_REVIEW or mean_conf < THRESH_NEEDS_REVIEW:
        overall_band = ReviewBand.REJECT
    elif min_conf < THRESH_AUTO_ACCEPT or mean_conf < THRESH_AUTO_ACCEPT:
        overall_band = ReviewBand.NEEDS_REVIEW
    else:
        overall_band = ReviewBand.AUTO_ACCEPT

    return ScoringSummary(
        mean_confidence=round(mean_conf, 4),
        min_confidence=round(min_conf, 4),
        review_band=overall_band,
        field_breakdowns=breakdowns,
    )
