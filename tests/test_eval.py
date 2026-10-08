"""Unit tests for the evaluation harness and metrics calculation."""

from decimal import Decimal

from co_extract.schema import ExtractedField, LineItem
from eval.run_eval import (
    are_fields_equal,
    evaluate_pipeline_on_dataset,
    match_line_items,
    normalize_val,
    run_full_evaluation_suite,
)


def test_normalize_val_helper():
    """Verify normalization handles decimals, strings, and dates."""
    assert normalize_val(Decimal("123.456")) == Decimal("123.46")
    assert normalize_val("  Hello   World  ") == "hello world"
    assert normalize_val(None) is None


def test_are_fields_equal():
    """Verify equality logic under normalization."""
    assert are_fields_equal(Decimal("100.00"), Decimal("100.005")) is True
    assert are_fields_equal(Decimal("100.00"), Decimal("101.00")) is False
    assert are_fields_equal("CO-001", "  co-001 ") is True
    assert are_fields_equal(None, None) is True
    assert are_fields_equal("CO-001", None) is False


def test_match_line_items():
    """Verify line item precision/recall matching logic."""
    item1 = LineItem(
        description=ExtractedField.from_value("Drywall 5/8 Type X"),
        amount=ExtractedField.from_value(Decimal("5075.00")),
    )
    item2 = LineItem(
        description=ExtractedField.from_value("Metal Framing"),
        amount=ExtractedField.from_value(Decimal("4320.00")),
    )

    # 1. Exact match
    tp, fp, fn = match_line_items([item1], [item1])
    assert tp == 1 and fp == 0 and fn == 0

    # 2. Predicted item with wrong amount
    item1_bad = LineItem(
        description=ExtractedField.from_value("Drywall 5/8 Type X"),
        amount=ExtractedField.from_value(Decimal("9999.00")),
    )
    tp, fp, fn = match_line_items([item1_bad], [item1])
    assert tp == 0 and fp == 1 and fn == 1

    # 3. Extra predicted item
    tp, fp, fn = match_line_items([item1, item2], [item1])
    assert tp == 1 and fp == 1 and fn == 0


def test_evaluate_pipeline_on_dataset_mock():
    """Verify evaluation runs across dataset and produces expected metrics."""
    report = evaluate_pipeline_on_dataset(provider="claude", mock=True)
    assert report.total_documents == 12
    assert report.field_accuracy >= 0.90
    assert report.hallucination_rate <= 0.05
    assert report.line_item_f1 >= 0.90
    assert report.validation_catch_rate >= 0.50
    assert len(report.calibration_buckets) == 3


def test_run_full_evaluation_suite():
    """Verify full evaluation suite runs and outputs markdown and json files."""
    reports, json_path, md_path = run_full_evaluation_suite(mock=True)
    assert "claude" in reports
    assert "gemini" in reports
    assert "both" in reports
    assert json_path.exists()
    assert md_path.exists()
    assert md_path.stat().st_size > 0
