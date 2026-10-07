"""Deterministic validation rules (V1 to V10) and grounding checks."""

import difflib
import re
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from co_extract.ingest import Document
from co_extract.schema import ChangeOrder, ExtractedField, StatusEnum

# Constants
MIN_SANE_YEAR = 2000
MAX_YEAR_OFFSET = 5
MIN_SCHEDULE_DAYS = -365
MAX_SCHEDULE_DAYS = 3650
FLOAT_TOLERANCE = Decimal("0.01")
STANDARD_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD"}


class ValidationIssue(BaseModel):
    """Detailed record of a validation rule failure."""

    rule_id: str = Field(description="Rule identifier, e.g. 'V1', 'V7'")
    field_path: str = Field(description="Dotted path to affected field, e.g. 'total_amount'")
    flag: str = Field(description="Machine-readable flag name, e.g. 'sum_mismatch'")
    message: str = Field(description="Human-readable description of the validation failure")


class ValidationReport(BaseModel):
    """Aggregated validation report across all rules."""

    is_valid: bool = Field(description="True if no rule violations occurred")
    issues: list[ValidationIssue] = Field(
        default_factory=list, description="List of all detected issues"
    )
    failed_rules: list[str] = Field(
        default_factory=list, description="Unique list of failed rule IDs"
    )


def _normalize_text_for_grounding(text: str) -> str:
    """Normalize text by lowercasing, replacing punctuation with spaces, and collapsing whitespace."""
    if not text:
        return ""
    # Replace punctuation and special characters with spaces
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(cleaned.split())


def check_grounding_match(source_text: str | None, document_text: str) -> tuple[float, bool]:
    """Check whether source_text appears within document_text.

    Returns:
        tuple of (score between 0.0 and 1.0, is_grounded boolean)
    """
    if not source_text or not source_text.strip():
        return 0.0, False

    clean_source = _normalize_text_for_grounding(source_text)
    clean_doc = _normalize_text_for_grounding(document_text)

    if not clean_source or not clean_doc:
        return 0.0, False

    # Exact normalized substring match
    if clean_source in clean_doc:
        return 1.0, True

    # If small word sequence, check if tokens exist in sequence or fuzzy match
    # Use SequenceMatcher on sliding window or ratio if text is short
    if len(clean_source) <= len(clean_doc):
        # Quick token sequence check
        source_words = clean_source.split()
        if len(source_words) >= 2:
            # Check if all words appear in doc in reasonable proximity
            first_word = source_words[0]
            if first_word in clean_doc:
                # Fuzzy ratio check against sliding window segments
                doc_words = clean_doc.split()
                n_words = len(source_words)
                best_ratio = 0.0
                for i in range(len(doc_words) - n_words + 1):
                    window = " ".join(doc_words[i : i + n_words])
                    ratio = difflib.SequenceMatcher(None, clean_source, window).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                    if best_ratio >= 0.85:
                        return 0.75, True
                if best_ratio >= 0.70:
                    return 0.5, True

    # Check direct sequence matcher ratio if source is short
    ratio = difflib.SequenceMatcher(None, clean_source, clean_doc).ratio()
    if ratio >= 0.80:
        return 0.75, True

    return 0.0, False


def _attach_flag(field: ExtractedField[Any], flag: str) -> None:
    """Safely append a flag to an ExtractedField if not already present."""
    if flag not in field.flags:
        field.flags.append(flag)


def validate_change_order(co: ChangeOrder, doc: Document | None = None) -> ValidationReport:
    """Execute validation rules V1 through V10 on the given ChangeOrder.

    Modifies the ChangeOrder fields in-place to attach diagnostic flags,
    and returns a ValidationReport.
    """
    issues: list[ValidationIssue] = []

    def record_issue(
        rule_id: str,
        field_path: str,
        flag: str,
        message: str,
        target_field: ExtractedField[Any] | None = None,
    ) -> None:
        issues.append(
            ValidationIssue(
                rule_id=rule_id,
                field_path=field_path,
                flag=flag,
                message=message,
            )
        )
        if target_field is not None:
            _attach_flag(target_field, flag)

    # ---------------------------------------------------------
    # V1: Line items sum equals total_amount
    # ---------------------------------------------------------
    if co.total_amount.value is not None and co.line_items:
        line_item_amounts = [
            item.amount.value for item in co.line_items if item.amount.value is not None
        ]
        if line_item_amounts:
            calc_sum = sum(line_item_amounts, Decimal("0.00"))
            diff = abs(calc_sum - co.total_amount.value)
            if diff > FLOAT_TOLERANCE:
                msg = (
                    f"Line items sum ({calc_sum}) does not match stated total_amount "
                    f"({co.total_amount.value}) with difference {diff}."
                )
                record_issue("V1", "total_amount", "sum_mismatch", msg, co.total_amount)

    # ---------------------------------------------------------
    # V2: quantity * unit_price == amount per line item
    # ---------------------------------------------------------
    for idx, item in enumerate(co.line_items):
        if (
            item.quantity.value is not None
            and item.unit_price.value is not None
            and item.amount.value is not None
        ):
            expected = item.quantity.value * item.unit_price.value
            diff = abs(expected - item.amount.value)
            if diff > FLOAT_TOLERANCE:
                msg = (
                    f"Line item {idx} calculation mismatch: quantity ({item.quantity.value}) * "
                    f"unit_price ({item.unit_price.value}) = {expected}, but amount is {item.amount.value}."
                )
                record_issue(
                    "V2", f"line_items[{idx}].amount", "line_calc_mismatch", msg, item.amount
                )

    # ---------------------------------------------------------
    # V3: revised_contract_sum == original_contract_sum + total_amount
    # ---------------------------------------------------------
    if (
        co.revised_contract_sum.value is not None
        and co.original_contract_sum.value is not None
        and co.total_amount.value is not None
    ):
        expected_revised = co.original_contract_sum.value + co.total_amount.value
        diff = abs(expected_revised - co.revised_contract_sum.value)
        if diff > FLOAT_TOLERANCE:
            msg = (
                f"Revised contract sum ({co.revised_contract_sum.value}) does not equal "
                f"original ({co.original_contract_sum.value}) + total ({co.total_amount.value}). "
                f"Expected {expected_revised}."
            )
            record_issue(
                "V3", "revised_contract_sum", "contract_sum_mismatch", msg, co.revised_contract_sum
            )

    # ---------------------------------------------------------
    # V4: Date sanity & sequence
    # ---------------------------------------------------------
    current_year = date.today().year
    max_sane_year = current_year + MAX_YEAR_OFFSET

    # Check date_issued
    if co.date_issued.value is not None:
        yr = co.date_issued.value.year
        if yr < MIN_SANE_YEAR or yr > max_sane_year:
            record_issue(
                "V4",
                "date_issued",
                "invalid_date_range",
                f"date_issued year ({yr}) outside sane range ({MIN_SANE_YEAR}..{max_sane_year}).",
                co.date_issued,
            )

    # Check new_completion_date
    if co.new_completion_date.value is not None:
        yr = co.new_completion_date.value.year
        if yr < MIN_SANE_YEAR or yr > max_sane_year:
            record_issue(
                "V4",
                "new_completion_date",
                "invalid_date_range",
                f"new_completion_date year ({yr}) outside sane range ({MIN_SANE_YEAR}..{max_sane_year}).",
                co.new_completion_date,
            )
        if co.date_issued.value is not None and co.new_completion_date.value < co.date_issued.value:
            record_issue(
                "V4",
                "new_completion_date",
                "completion_before_issued",
                f"new_completion_date ({co.new_completion_date.value}) is before date_issued ({co.date_issued.value}).",
                co.new_completion_date,
            )

    # ---------------------------------------------------------
    # V5: schedule_impact_days is within sane bounds
    # ---------------------------------------------------------
    if co.schedule_impact_days.value is not None:
        days = co.schedule_impact_days.value
        if days < MIN_SCHEDULE_DAYS or days > MAX_SCHEDULE_DAYS:
            record_issue(
                "V5",
                "schedule_impact_days",
                "unrealistic_schedule_impact",
                f"schedule_impact_days ({days}) outside sane bound ({MIN_SCHEDULE_DAYS}..{MAX_SCHEDULE_DAYS}).",
                co.schedule_impact_days,
            )

    # ---------------------------------------------------------
    # V6: status enum & approved status requires signed approval
    # ---------------------------------------------------------
    if co.status.value is not None:
        if co.status.value == StatusEnum.APPROVED:
            has_signed = any(
                appr.signed.value is True for appr in co.approvals if appr.signed.value is not None
            )
            if not has_signed:
                record_issue(
                    "V6",
                    "status",
                    "approved_without_signatures",
                    "Change order is marked 'approved' but contains no signed approvals.",
                    co.status,
                )

    # ---------------------------------------------------------
    # V7: Grounding checks (source_text appears in document)
    # ---------------------------------------------------------
    if doc and doc.text:
        # Check all scalar fields with non-null values
        fields_to_check: list[tuple[str, ExtractedField[Any]]] = [
            ("co_number", co.co_number),
            ("revision", co.revision),
            ("project_name", co.project_name),
            ("project_number", co.project_number),
            ("owner", co.owner),
            ("contractor", co.contractor),
            ("subcontractor", co.subcontractor),
            ("reason", co.reason),
            ("description", co.description),
            ("total_amount", co.total_amount),
            ("original_contract_sum", co.original_contract_sum),
            ("revised_contract_sum", co.revised_contract_sum),
        ]
        for field_name, fld in fields_to_check:
            if fld.value is not None:
                score, is_grounded = check_grounding_match(fld.source_text, doc.text)
                if not is_grounded:
                    record_issue(
                        "V7",
                        field_name,
                        "not_grounded",
                        f"Field '{field_name}' source_text '{fld.source_text}' not grounded in document text.",
                        fld,
                    )

        # Check line items grounding
        for idx, item in enumerate(co.line_items):
            if item.amount.value is not None:
                score, is_grounded = check_grounding_match(item.amount.source_text, doc.text)
                if not is_grounded:
                    record_issue(
                        "V7",
                        f"line_items[{idx}].amount",
                        "not_grounded",
                        f"Line item {idx} amount source_text '{item.amount.source_text}' not grounded in document.",
                        item.amount,
                    )

    # ---------------------------------------------------------
    # V8: CO number matches plausible pattern & != project_number
    # ---------------------------------------------------------
    if co.co_number.value is not None:
        co_val = co.co_number.value.strip()
        if (
            co.project_number.value is not None
            and co_val.lower() == co.project_number.value.strip().lower()
        ):
            record_issue(
                "V8",
                "co_number",
                "co_equals_project_number",
                f"co_number '{co_val}' is identical to project_number.",
                co.co_number,
            )
        # Check plausible pattern: not pure spaces or just symbols
        if len(co_val) < 1 or re.match(r"^[^a-zA-Z0-9]+$", co_val):
            record_issue(
                "V8",
                "co_number",
                "invalid_co_format",
                f"co_number '{co_val}' is not a plausible identifier.",
                co.co_number,
            )

    # ---------------------------------------------------------
    # V9: Currency & amount format parsing
    # ---------------------------------------------------------
    if co.currency.value is not None:
        curr = co.currency.value.strip().upper()
        if curr not in STANDARD_CURRENCIES:
            record_issue(
                "V9",
                "currency",
                "invalid_currency",
                f"Currency '{co.currency.value}' is not a standard recognized currency code.",
                co.currency,
            )

    # ---------------------------------------------------------
    # V10: Approval dates not before date_issued
    # ---------------------------------------------------------
    if co.date_issued.value is not None:
        for idx, appr in enumerate(co.approvals):
            if appr.date.value is not None and appr.date.value < co.date_issued.value:
                record_issue(
                    "V10",
                    f"approvals[{idx}].date",
                    "approval_before_issue_date",
                    f"Approval {idx} date ({appr.date.value}) is before date_issued ({co.date_issued.value}).",
                    appr.date,
                )

    failed_rule_ids = sorted({iss.rule_id for iss in issues})
    return ValidationReport(
        is_valid=len(issues) == 0,
        issues=issues,
        failed_rules=failed_rule_ids,
    )
