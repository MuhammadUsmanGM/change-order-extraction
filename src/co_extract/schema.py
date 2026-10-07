from datetime import date as dt_date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class DirectionEnum(StrEnum):
    """Direction of the change order amount."""

    INCREASE = "increase"
    DECREASE = "decrease"
    NO_CHANGE = "no-change"
    UNKNOWN = "unknown"


class StatusEnum(StrEnum):
    """Approval status of the change order."""

    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class ExtractedField(BaseModel, Generic[T]):
    """Generic wrapper for any extracted field with confidence and source grounding."""

    value: T | None = Field(default=None, description="Extracted value or null if absent")
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0",
    )
    source_text: str | None = Field(
        default=None,
        description="Verbatim snippet from document supporting this extraction",
    )
    flags: list[str] = Field(
        default_factory=list,
        description="Validation and discrepancy flags (e.g., 'not_grounded', 'sum_mismatch')",
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @classmethod
    def from_value(
        cls,
        value: T | None,
        confidence: float = 1.0,
        source_text: str | None = None,
        flags: list[str] | None = None,
    ) -> "ExtractedField[T]":
        """Convenience factory method to wrap a value."""
        return cls(
            value=value,
            confidence=confidence,
            source_text=source_text,
            flags=flags or [],
        )


class LineItem(BaseModel):
    """Individual line item or work item within a change order."""

    description: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="Scope or item description",
    )
    quantity: ExtractedField[Decimal] = Field(
        default_factory=ExtractedField[Decimal],
        description="Quantity of work or materials",
    )
    unit: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="Unit of measure (e.g., LF, EA, SQFT, HR)",
    )
    unit_price: ExtractedField[Decimal] = Field(
        default_factory=ExtractedField[Decimal],
        description="Unit cost or unit rate",
    )
    amount: ExtractedField[Decimal] = Field(
        default_factory=ExtractedField[Decimal],
        description="Total monetary amount for this line item",
    )
    cost_code: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="CSI MasterFormat or accounting cost code",
    )


class Approval(BaseModel):
    """Sign-off or approval record."""

    name: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="Signatory person name",
    )
    role: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="Role or title (e.g., Architect, Owner Rep, Contractor)",
    )
    date: ExtractedField[dt_date] = Field(
        default_factory=ExtractedField[dt_date],
        description="Date of signature (ISO YYYY-MM-DD)",
    )
    signed: ExtractedField[bool] = Field(
        default_factory=ExtractedField[bool],
        description="Whether a valid signature or mark is present",
    )


class ChangeOrder(BaseModel):
    """Complete structured representation of a Change Order."""

    # Identity
    co_number: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="Change order number / identifier",
    )
    revision: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="Revision number or letter if applicable",
    )
    date_issued: ExtractedField[dt_date] = Field(
        default_factory=ExtractedField[dt_date],
        description="Date issued (ISO YYYY-MM-DD)",
    )
    references: ExtractedField[list[str]] = Field(
        default_factory=ExtractedField[list[str]],
        description="Related references such as RFI, ASI, PCO, COR numbers",
    )

    # Parties
    project_name: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="Project title / name",
    )
    project_number: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="Internal or contract project number",
    )
    owner: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="Owner or client organization",
    )
    contractor: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="General contractor",
    )
    subcontractor: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="Subcontractor or vendor",
    )

    # Description
    reason: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="Stated justification / reason for change",
    )
    description: ExtractedField[str] = Field(
        default_factory=ExtractedField[str],
        description="Detailed description of changed scope",
    )

    # Financials
    total_amount: ExtractedField[Decimal] = Field(
        default_factory=ExtractedField[Decimal],
        description="Total change order dollar amount",
    )
    currency: ExtractedField[str] = Field(
        default_factory=lambda: ExtractedField[str](value="USD"),
        description="Currency code (e.g., USD, EUR, CAD)",
    )
    direction: ExtractedField[DirectionEnum] = Field(
        default_factory=ExtractedField[DirectionEnum],
        description="Amount direction (increase, decrease, no-change)",
    )
    original_contract_sum: ExtractedField[Decimal] = Field(
        default_factory=ExtractedField[Decimal],
        description="Original contract value before this change",
    )
    revised_contract_sum: ExtractedField[Decimal] = Field(
        default_factory=ExtractedField[Decimal],
        description="Updated contract sum including this change",
    )

    # Line Items
    line_items: list[LineItem] = Field(
        default_factory=list,
        description="Detailed list of line items",
    )

    # Schedule
    schedule_impact_days: ExtractedField[int] = Field(
        default_factory=ExtractedField[int],
        description="Schedule change in calendar days (positive or negative)",
    )
    new_completion_date: ExtractedField[dt_date] = Field(
        default_factory=ExtractedField[dt_date],
        description="New project substantial completion date",
    )

    # Status & Approvals
    status: ExtractedField[StatusEnum] = Field(
        default_factory=ExtractedField[StatusEnum],
        description="Current workflow status (draft, pending, approved, rejected)",
    )
    approvals: list[Approval] = Field(
        default_factory=list,
        description="List of signatories and approval timestamps",
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


def get_change_order_json_schema() -> dict[str, Any]:
    """Return JSON Schema representation of ChangeOrder suitable for LLM structured output."""
    return ChangeOrder.model_json_schema()
