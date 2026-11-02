"""Unit tests for the CustomOperator domain model."""

from datetime import UTC, datetime
from typing import Any

import pytest

from docpipe.core.custom_operators.models import CustomOperator, CustomOperatorStatus
from docpipe.exceptions.docpipe_exceptions import CustomOperatorInvalidDataException


def _make_operator(**overrides: Any) -> CustomOperator:
    """Build a valid CustomOperator, optionally overriding single fields."""
    fields: dict[str, Any] = {
        "name": "Invoice Extractor",
        "description": "Extracts invoice fields",
        "short_name": "invoice_extractor",
        "status": CustomOperatorStatus.VALIDATED,
        "message": "Operator validated and stored successfully",
        "operator_file": "invoice_extractor.py",
    }
    fields.update(overrides)
    return CustomOperator(**fields)


class TestCustomOperatorValidate:
    """Test suite for CustomOperator.validate invariants."""

    def test_validate_accepts_complete_operator(self) -> None:
        """A fully populated operator passes validation without raising."""
        _make_operator().validate()

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("name", "", "Operator name cannot be empty"),
            ("name", "   ", "Operator name cannot be empty"),
            ("short_name", "", "Operator short_name cannot be empty"),
            ("short_name", "\t", "Operator short_name cannot be empty"),
            ("operator_file", "", "Operator file name cannot be empty"),
            ("operator_file", "  ", "Operator file name cannot be empty"),
        ],
    )
    def test_validate_rejects_blank_required_fields(self, *, field: str, value: str, message: str) -> None:
        """Empty or whitespace-only name, short_name and operator_file are rejected with the field name."""
        operator = _make_operator(**{field: value})

        with pytest.raises(CustomOperatorInvalidDataException, match=message) as exc_info:
            operator.validate()

        assert exc_info.value.field_name == field

    def test_validate_accepts_status_given_as_plain_string(self) -> None:
        """A status stored as its plain string value is accepted."""
        _make_operator(status="pending").validate()

    def test_validate_rejects_unknown_status(self) -> None:
        """A status outside CustomOperatorStatus is rejected and chained to the ValueError."""
        operator = _make_operator(status="archived")

        with pytest.raises(CustomOperatorInvalidDataException, match="Invalid operator status: archived") as exc_info:
            operator.validate()

        assert exc_info.value.field_name == "status"
        assert isinstance(exc_info.value.__cause__, ValueError)


class TestCustomOperatorSerialization:
    """Test suite for CustomOperator.to_dict / from_dict."""

    def test_to_dict_from_dict_round_trip_preserves_all_fields(self) -> None:
        """Serializing and deserializing yields an equal operator, including timestamps and metadata."""
        created = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        updated = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)
        operator = _make_operator(
            id="7c9e6679-7425-40de-944b-e07fc1f90ae7",
            created_at=created,
            updated_at=updated,
            metadata={"category": "Extract", "class_name": "InvoiceExtractor"},
        )

        data = operator.to_dict()

        assert data["status"] == "validated"
        assert data["created_at"] == created.isoformat()
        assert data["updated_at"] == updated.isoformat()
        assert CustomOperator.from_dict(data=data) == operator

    def test_to_dict_serializes_plain_string_status_and_missing_timestamps(self) -> None:
        """A plain string status is kept as-is and absent timestamps serialize to None."""
        data = _make_operator(status="pending").to_dict()

        assert data["status"] == "pending"
        assert data["created_at"] is None
        assert data["updated_at"] is None

    def test_from_dict_maps_unknown_status_to_invalid(self) -> None:
        """A persisted status that is no longer known is surfaced as INVALID instead of failing."""
        operator = CustomOperator.from_dict(data={"name": "n", "short_name": "s", "status": "archived"})

        assert operator.status == CustomOperatorStatus.INVALID

    def test_from_dict_applies_defaults_for_missing_fields(self) -> None:
        """Missing keys fall back to empty strings, PENDING status, no timestamps and empty metadata."""
        operator = CustomOperator.from_dict(data={})

        assert operator.id is None
        assert operator.name == ""
        assert operator.description == ""
        assert operator.short_name == ""
        assert operator.message == ""
        assert operator.operator_file == ""
        assert operator.status == CustomOperatorStatus.PENDING
        assert operator.created_at is None
        assert operator.updated_at is None
        assert operator.metadata == {}

    def test_from_dict_keeps_datetime_objects_unchanged(self) -> None:
        """Timestamps that are already datetime objects are used as-is."""
        created = datetime(2026, 5, 6, tzinfo=UTC)

        operator = CustomOperator.from_dict(data={"created_at": created, "updated_at": None})

        assert operator.created_at is created
        assert operator.updated_at is None
