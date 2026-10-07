"""Unit tests for confidence scoring, calibration, and agreement."""

from datetime import date
from decimal import Decimal

from co_extract.confidence import (
    ReviewBand,
    calibrate_and_score_change_order,
    check_values_agree,
    compute_field_confidence,
)
from co_extract.ingest import Document
from co_extract.schema import ChangeOrder, ExtractedField
from co_extract.validate import validate_change_order


def test_compute_field_confidence_clean():
    """Verify clean field scores in AUTO_ACCEPT band."""
    breakdown = compute_field_confidence(
        model_conf=0.95,
        grounding_score=1.0,
        has_validation_flag=False,
        agreement_score=1.0,
        is_value_present=True,
    )
    # 0.30*0.95 + 0.25*1.0 + 0.25*1.0 + 0.20*1.0 = 0.285 + 0.25 + 0.25 + 0.20 = 0.985
    assert breakdown.final_score >= 0.95
    assert breakdown.review_band == ReviewBand.AUTO_ACCEPT
    assert breakdown.capped_reason is None


def test_ungrounded_override_cap():
    """Verify ungrounded value is capped at 0.30."""
    breakdown = compute_field_confidence(
        model_conf=1.0,
        grounding_score=0.0,  # ungrounded
        has_validation_flag=False,
        agreement_score=1.0,
        is_value_present=True,
    )
    assert breakdown.final_score == 0.30
    assert breakdown.capped_reason == "ungrounded_value"
    assert breakdown.review_band == ReviewBand.REJECT


def test_disagreement_override_cap():
    """Verify provider disagreement caps score at 0.50."""
    breakdown = compute_field_confidence(
        model_conf=1.0,
        grounding_score=1.0,
        has_validation_flag=False,
        agreement_score=0.0,  # disagreement
        is_value_present=True,
    )
    assert breakdown.final_score == 0.50
    assert breakdown.capped_reason == "providers_disagree"
    assert breakdown.review_band == ReviewBand.REJECT


def test_check_values_agree():
    """Verify value normalization and agreement."""
    # Decimals
    assert check_values_agree(Decimal("100.00"), Decimal("100.00")) is True
    assert check_values_agree(Decimal("100.00"), Decimal("100.05")) is False

    # Strings
    assert check_values_agree("CO-007", "  co-007 ") is True
    assert check_values_agree("CO-007", "CO-008") is False

    # Dates
    assert check_values_agree(date(2026, 5, 1), date(2026, 5, 1)) is True
    assert check_values_agree(date(2026, 5, 1), date(2026, 5, 2)) is False

    # None handling
    assert check_values_agree(None, None) is True
    assert check_values_agree("value", None) is False


def test_calibrate_and_score_dual_provider_agreement():
    """Verify calibrate_and_score_change_order cross-provider comparison."""
    doc = Document(
        text="Change Order CO-100 total $5,000.00 approved.",
        pages=["Change Order CO-100 total $5,000.00 approved."],
    )

    # Provider 1 (Claude)
    co1 = ChangeOrder(
        co_number=ExtractedField.from_value("CO-100", 0.95, "CO-100"),
        total_amount=ExtractedField.from_value(Decimal("5000.00"), 0.95, "$5,000.00"),
    )

    # Provider 2 (Gemini agrees on co_number, disagrees on total_amount)
    co2 = ChangeOrder(
        co_number=ExtractedField.from_value("co-100", 0.95, "CO-100"),
        total_amount=ExtractedField.from_value(Decimal("6000.00"), 0.95, "$6,000.00"),
    )

    val_report = validate_change_order(co1, doc=doc)
    summary = calibrate_and_score_change_order(
        co=co1,
        doc=doc,
        validation_report=val_report,
        comparison_co=co2,
    )

    # co_number agreed: score should be high
    assert co1.co_number.confidence >= 0.85
    # total_amount disagreed: capped at 0.50 and flagged
    assert co1.total_amount.confidence == 0.50
    assert "providers_disagree" in co1.total_amount.flags
    assert summary.review_band == ReviewBand.REJECT
