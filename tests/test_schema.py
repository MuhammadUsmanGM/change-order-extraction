"""Unit tests for Pydantic schema and data models."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from co_extract.schema import (
    Approval,
    ChangeOrder,
    DirectionEnum,
    ExtractedField,
    LineItem,
    StatusEnum,
    get_change_order_json_schema,
)


def test_extracted_field_defaults():
    """Verify default empty behavior of ExtractedField."""
    field = ExtractedField[str]()
    assert field.value is None
    assert field.confidence == 1.0
    assert field.source_text is None
    assert field.flags == []


def test_extracted_field_custom_values():
    """Verify custom attributes and factory method."""
    field = ExtractedField.from_value(
        value="CO-102",
        confidence=0.95,
        source_text="Change Order # 102",
        flags=["ocr_repaired"],
    )
    assert field.value == "CO-102"
    assert field.confidence == 0.95
    assert field.source_text == "Change Order # 102"
    assert field.flags == ["ocr_repaired"]


def test_confidence_validation():
    """Verify confidence must be between 0.0 and 1.0."""
    with pytest.raises(ValidationError):
        ExtractedField[str](confidence=1.5)

    with pytest.raises(ValidationError):
        ExtractedField[str](confidence=-0.1)


def test_decimal_precision_preservation():
    """Verify money fields use Decimal and do not suffer IEEE-754 float drift."""
    amt = Decimal("14250.85")
    co = ChangeOrder(
        total_amount=ExtractedField[Decimal](value=amt),
        original_contract_sum=ExtractedField[Decimal](value=Decimal("1000000.00")),
        revised_contract_sum=ExtractedField[Decimal](value=Decimal("1014250.85")),
    )
    assert co.total_amount.value == Decimal("14250.85")
    json_data = co.model_dump_json()
    reconstructed = ChangeOrder.model_validate_json(json_data)
    assert reconstructed.total_amount.value == amt
    assert isinstance(reconstructed.total_amount.value, Decimal)


def test_negative_decimal_handling():
    """Verify deductive change order amounts (negative decimals)."""
    co = ChangeOrder(
        total_amount=ExtractedField[Decimal](value=Decimal("-3500.00")),
        direction=ExtractedField[DirectionEnum](value=DirectionEnum.DECREASE),
    )
    assert co.total_amount.value == Decimal("-3500.00")
    assert co.direction.value == DirectionEnum.DECREASE


def test_date_parsing_and_serialization():
    """Verify date parsing and serialization."""
    co = ChangeOrder(
        date_issued=ExtractedField[date](value=date(2026, 4, 15)),
        new_completion_date=ExtractedField[date](value=date(2026, 9, 30)),
    )
    assert co.date_issued.value == date(2026, 4, 15)
    json_str = co.model_dump_json()
    reconstructed = ChangeOrder.model_validate_json(json_str)
    assert reconstructed.date_issued.value == date(2026, 4, 15)
    assert reconstructed.new_completion_date.value == date(2026, 9, 30)


def test_full_change_order_round_trip():
    """Verify full change order serialization and deserialization."""
    line_item = LineItem(
        description=ExtractedField.from_value("Additional drywall installation", 0.98),
        quantity=ExtractedField.from_value(Decimal("450.00"), 0.95),
        unit=ExtractedField.from_value("SQFT", 0.99),
        unit_price=ExtractedField.from_value(Decimal("12.50"), 0.95),
        amount=ExtractedField.from_value(Decimal("5625.00"), 0.98),
        cost_code=ExtractedField.from_value("09-21-16", 0.9),
    )
    approval = Approval(
        name=ExtractedField.from_value("Jane Doe", 0.99),
        role=ExtractedField.from_value("Project Manager", 0.95),
        date=ExtractedField.from_value(date(2026, 4, 18), 0.95),
        signed=ExtractedField.from_value(True, 1.0),
    )
    co = ChangeOrder(
        co_number=ExtractedField.from_value("CO-007", 0.99, "Change Order: CO-007"),
        revision=ExtractedField.from_value("0", 0.9),
        date_issued=ExtractedField.from_value(date(2026, 4, 15)),
        references=ExtractedField.from_value(["RFI-042", "PCO-015"]),
        project_name=ExtractedField.from_value("Apex Tower", 0.95),
        project_number=ExtractedField.from_value("PRJ-2026-01", 0.95),
        owner=ExtractedField.from_value("Apex Real Estate Partners", 0.95),
        contractor=ExtractedField.from_value("BuildCorp Inc.", 0.95),
        subcontractor=ExtractedField.from_value("Drywall Masters LLC", 0.9),
        reason=ExtractedField.from_value("Owner requested layout revision", 0.92),
        description=ExtractedField.from_value("Furnish and install extra partition wall", 0.92),
        total_amount=ExtractedField.from_value(Decimal("5625.00"), 0.98),
        currency=ExtractedField.from_value("USD"),
        direction=ExtractedField.from_value(DirectionEnum.INCREASE),
        original_contract_sum=ExtractedField.from_value(Decimal("500000.00")),
        revised_contract_sum=ExtractedField.from_value(Decimal("505625.00")),
        line_items=[line_item],
        schedule_impact_days=ExtractedField.from_value(3),
        new_completion_date=ExtractedField.from_value(date(2026, 11, 15)),
        status=ExtractedField.from_value(StatusEnum.APPROVED),
        approvals=[approval],
    )

    dumped = co.model_dump_json()
    loaded = ChangeOrder.model_validate_json(dumped)

    assert loaded.co_number.value == "CO-007"
    assert loaded.references.value == ["RFI-042", "PCO-015"]
    assert len(loaded.line_items) == 1
    assert loaded.line_items[0].amount.value == Decimal("5625.00")
    assert len(loaded.approvals) == 1
    assert loaded.approvals[0].signed.value is True
    assert loaded.status.value == StatusEnum.APPROVED


def test_schema_export():
    """Verify that JSON Schema export succeeds and contains expected keys."""
    schema = get_change_order_json_schema()
    assert isinstance(schema, dict)
    assert schema.get("type") == "object"
    assert "properties" in schema
    assert "co_number" in schema["properties"]
    assert "total_amount" in schema["properties"]
    assert "line_items" in schema["properties"]
