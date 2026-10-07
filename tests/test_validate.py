"""Unit tests for validation rules V1 through V10."""

from datetime import date
from decimal import Decimal

from co_extract.ingest import Document
from co_extract.schema import (
    Approval,
    ChangeOrder,
    ExtractedField,
    LineItem,
    StatusEnum,
)
from co_extract.validate import validate_change_order


def test_v1_line_items_sum():
    """V1: Sum of line-item amounts equals total_amount."""
    # Passing case
    co_pass = ChangeOrder(
        total_amount=ExtractedField.from_value(Decimal("300.00")),
        line_items=[
            LineItem(amount=ExtractedField.from_value(Decimal("100.00"))),
            LineItem(amount=ExtractedField.from_value(Decimal("200.00"))),
        ],
    )
    report_pass = validate_change_order(co_pass)
    assert "V1" not in report_pass.failed_rules
    assert "sum_mismatch" not in co_pass.total_amount.flags

    # Failing case
    co_fail = ChangeOrder(
        total_amount=ExtractedField.from_value(Decimal("300.00")),
        line_items=[
            LineItem(amount=ExtractedField.from_value(Decimal("100.00"))),
            LineItem(amount=ExtractedField.from_value(Decimal("150.00"))),
        ],
    )
    report_fail = validate_change_order(co_fail)
    assert "V1" in report_fail.failed_rules
    assert "sum_mismatch" in co_fail.total_amount.flags


def test_v2_line_item_math():
    """V2: quantity * unit_price equals amount per line item."""
    # Passing case
    co_pass = ChangeOrder(
        line_items=[
            LineItem(
                quantity=ExtractedField.from_value(Decimal("10.0")),
                unit_price=ExtractedField.from_value(Decimal("25.00")),
                amount=ExtractedField.from_value(Decimal("250.00")),
            )
        ]
    )
    report_pass = validate_change_order(co_pass)
    assert "V2" not in report_pass.failed_rules

    # Failing case
    co_fail = ChangeOrder(
        line_items=[
            LineItem(
                quantity=ExtractedField.from_value(Decimal("10.0")),
                unit_price=ExtractedField.from_value(Decimal("25.00")),
                amount=ExtractedField.from_value(Decimal("200.00")),
            )
        ]
    )
    report_fail = validate_change_order(co_fail)
    assert "V2" in report_fail.failed_rules
    assert "line_calc_mismatch" in co_fail.line_items[0].amount.flags


def test_v3_contract_sum_continuity():
    """V3: revised_contract_sum == original_contract_sum + total_amount."""
    # Passing case
    co_pass = ChangeOrder(
        original_contract_sum=ExtractedField.from_value(Decimal("1000.00")),
        total_amount=ExtractedField.from_value(Decimal("250.00")),
        revised_contract_sum=ExtractedField.from_value(Decimal("1250.00")),
    )
    report_pass = validate_change_order(co_pass)
    assert "V3" not in report_pass.failed_rules

    # Failing case
    co_fail = ChangeOrder(
        original_contract_sum=ExtractedField.from_value(Decimal("1000.00")),
        total_amount=ExtractedField.from_value(Decimal("250.00")),
        revised_contract_sum=ExtractedField.from_value(Decimal("1500.00")),
    )
    report_fail = validate_change_order(co_fail)
    assert "V3" in report_fail.failed_rules
    assert "contract_sum_mismatch" in co_fail.revised_contract_sum.flags


def test_v4_date_sanity_and_sequence():
    """V4: Valid date range and completion date after issue date."""
    # Passing case
    co_pass = ChangeOrder(
        date_issued=ExtractedField.from_value(date(2026, 3, 1)),
        new_completion_date=ExtractedField.from_value(date(2026, 6, 1)),
    )
    report_pass = validate_change_order(co_pass)
    assert "V4" not in report_pass.failed_rules

    # Failing sequence: completion before issued
    co_fail_seq = ChangeOrder(
        date_issued=ExtractedField.from_value(date(2026, 6, 1)),
        new_completion_date=ExtractedField.from_value(date(2026, 3, 1)),
    )
    report_fail_seq = validate_change_order(co_fail_seq)
    assert "V4" in report_fail_seq.failed_rules
    assert "completion_before_issued" in co_fail_seq.new_completion_date.flags

    # Failing year range
    co_fail_yr = ChangeOrder(
        date_issued=ExtractedField.from_value(date(1985, 1, 1)),
    )
    report_fail_yr = validate_change_order(co_fail_yr)
    assert "V4" in report_fail_yr.failed_rules
    assert "invalid_date_range" in co_fail_yr.date_issued.flags


def test_v5_schedule_impact_bounds():
    """V5: schedule_impact_days is within sane bounds."""
    # Passing case
    co_pass = ChangeOrder(schedule_impact_days=ExtractedField.from_value(14))
    report_pass = validate_change_order(co_pass)
    assert "V5" not in report_pass.failed_rules

    # Failing case (e.g. 100,000 days)
    co_fail = ChangeOrder(schedule_impact_days=ExtractedField.from_value(100000))
    report_fail = validate_change_order(co_fail)
    assert "V5" in report_fail.failed_rules
    assert "unrealistic_schedule_impact" in co_fail.schedule_impact_days.flags


def test_v6_status_and_signed_approvals():
    """V6: Approved status requires at least one signed approval."""
    # Passing case: approved with signed approval
    co_pass = ChangeOrder(
        status=ExtractedField.from_value(StatusEnum.APPROVED),
        approvals=[Approval(signed=ExtractedField.from_value(True))],
    )
    report_pass = validate_change_order(co_pass)
    assert "V6" not in report_pass.failed_rules

    # Failing case: approved with no signed approval
    co_fail = ChangeOrder(
        status=ExtractedField.from_value(StatusEnum.APPROVED),
        approvals=[Approval(signed=ExtractedField.from_value(False))],
    )
    report_fail = validate_change_order(co_fail)
    assert "V6" in report_fail.failed_rules
    assert "approved_without_signatures" in co_fail.status.flags


def test_v7_grounding_verification():
    """V7: Check grounding against document text."""
    doc = Document(
        text="Apex Tower Change Order CO-005 total amount $12,500.00 approved.",
        pages=["Apex Tower Change Order CO-005 total amount $12,500.00 approved."],
    )

    # Passing case: grounded snippet
    co_pass = ChangeOrder(
        co_number=ExtractedField.from_value("CO-005", source_text="CO-005"),
        total_amount=ExtractedField.from_value(Decimal("12500.00"), source_text="$12,500.00"),
    )
    report_pass = validate_change_order(co_pass, doc=doc)
    assert "V7" not in report_pass.failed_rules

    # Failing case: hallucinated value not in document
    co_fail = ChangeOrder(
        co_number=ExtractedField.from_value("CO-999", source_text="CO-999 Hallucinated"),
    )
    report_fail = validate_change_order(co_fail, doc=doc)
    assert "V7" in report_fail.failed_rules
    assert "not_grounded" in co_fail.co_number.flags


def test_v8_co_number_patterns():
    """V8: CO number matches pattern and does not equal project_number."""
    # Passing case
    co_pass = ChangeOrder(
        co_number=ExtractedField.from_value("CO-12"),
        project_number=ExtractedField.from_value("PRJ-800"),
    )
    report_pass = validate_change_order(co_pass)
    assert "V8" not in report_pass.failed_rules

    # Failing case: co_number equals project_number
    co_fail = ChangeOrder(
        co_number=ExtractedField.from_value("PRJ-800"),
        project_number=ExtractedField.from_value("PRJ-800"),
    )
    report_fail = validate_change_order(co_fail)
    assert "V8" in report_fail.failed_rules
    assert "co_equals_project_number" in co_fail.co_number.flags


def test_v9_currency_format():
    """V9: Currency code is standard."""
    # Passing case
    co_pass = ChangeOrder(currency=ExtractedField.from_value("USD"))
    report_pass = validate_change_order(co_pass)
    assert "V9" not in report_pass.failed_rules

    # Failing case
    co_fail = ChangeOrder(currency=ExtractedField.from_value("XYZ_FAKE"))
    report_fail = validate_change_order(co_fail)
    assert "V9" in report_fail.failed_rules
    assert "invalid_currency" in co_fail.currency.flags


def test_v10_approval_date_sequencing():
    """V10: Approval date cannot be earlier than date_issued."""
    # Passing case
    co_pass = ChangeOrder(
        date_issued=ExtractedField.from_value(date(2026, 5, 10)),
        approvals=[Approval(date=ExtractedField.from_value(date(2026, 5, 12)))],
    )
    report_pass = validate_change_order(co_pass)
    assert "V10" not in report_pass.failed_rules

    # Failing case
    co_fail = ChangeOrder(
        date_issued=ExtractedField.from_value(date(2026, 5, 10)),
        approvals=[Approval(date=ExtractedField.from_value(date(2026, 5, 5)))],
    )
    report_fail = validate_change_order(co_fail)
    assert "V10" in report_fail.failed_rules
    assert "approval_before_issue_date" in co_fail.approvals[0].date.flags
