# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Service layer for custom operator management."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docpipe.core.constants.constants import OrchestratorType
from docpipe.core.custom_operators.file_store import CustomOperatorFileStore, LocalFileStore
from docpipe.core.custom_operators.models import CustomOperator, CustomOperatorStatus
from docpipe.core.custom_operators.validation import validate_operator_file
from docpipe.core.orchestration.operator_factory import OperatorFactory, OperatorFactoryProvider
from docpipe.exceptions.docpipe_exceptions import (
    CustomOperatorAlreadyExistsException,
    CustomOperatorInvalidDataException,
    CustomOperatorNotFoundException,
    CustomOperatorsDisabledException,
)
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage
from docpipe.storage.interfaces.key_value_storage_port import KeyValueStoragePort
from docpipe.utils.infrastructure.filesystem import get_data_path
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

CUSTOM_OPERATORS_COLLECTION = "custom_operators"


class CustomOperatorService:
    """Service coordinating custom operator CRUD and lifecycle operations."""

    def __init__(
        self,
        *,
        file_store: CustomOperatorFileStore | None = None,
        metadata_storage: KeyValueStoragePort | None = None,
    ) -> None:
        """Initialize the custom operator service.

        Args:
            file_store: Pluggable file storage (defaults to LocalFileStore)
            metadata_storage: Pluggable metadata key-value storage (defaults to KeyValueFileSystemStorage)
        """
        self.file_store = file_store or LocalFileStore()
        self.metadata_storage = metadata_storage or KeyValueFileSystemStorage(
            base_dir=get_data_path(),
        )

    def _validate_uuid(self, *, operator_id: str) -> None:
        """Validate that operator_id is a valid UUID v4."""
        try:
            val = uuid.UUID(operator_id, version=4)
            if str(val) != operator_id:
                raise ValueError("UUID string format mismatch")
        except Exception as e:
            raise CustomOperatorInvalidDataException(
                message=f"Invalid operator_id '{operator_id}': must be a valid UUID v4",
                field_name="operator_id",
            ) from e

    @staticmethod
    def _require_custom_operators_enabled() -> None:
        """Refuse to store executable operator code that could never be loaded."""
        if not OperatorFactory.resolve_enable_custom_operators(enable_custom_operators=None):
            raise CustomOperatorsDisabledException(
                message=(
                    "Custom operators are disabled, so the operator was not stored. "
                    "Set DOCPIPE_ENABLE_CUSTOM_OPERATORS=true to enable them."
                )
            )

    def _refresh_operator_factories(self) -> None:
        """Safely refresh the existing cached operator factory in the current process."""
        if not OperatorFactory.resolve_enable_custom_operators(enable_custom_operators=None):
            logger.info("Custom operators are disabled; skipping operator factory refresh")
            return
        try:
            factory = OperatorFactoryProvider.get_operator_factory(orchestrator=OrchestratorType.PYTHON)
            factory.refresh_operators()
            logger.info("Refreshed operator factory after custom operator modification")
        except Exception as e:
            logger.warning("Failed to refresh operator factory: %s", e)

    def create_operator(
        self,
        *,
        name: str,
        description: str,
        operator_file_path: Path,
        original_filename: str | None = None,
    ) -> CustomOperator:
        """Validate, store, and register a new custom operator.

        Args:
            name: Human-readable name
            description: Description of the operator
            operator_file_path: Path to the uploaded .py file
            original_filename: Original filename from the upload (used for storage and metadata).
                               Falls back to operator_file_path.name if not provided.

        Returns:
            Created CustomOperator instance
        """
        self._require_custom_operators_enabled()
        if not name or not name.strip():
            raise CustomOperatorInvalidDataException(message="Operator name cannot be empty", field_name="name")

        # 1. Run static AST validation
        validation_info = validate_operator_file(operator_file_path=operator_file_path)
        short_name = validation_info["short_name"]

        # 2. Check for short_name collision across existing custom operators
        existing_operators = self.list_operators()
        for existing in existing_operators:
            if existing.short_name == short_name:
                raise CustomOperatorAlreadyExistsException(
                    message=f"Custom operator with short_name '{short_name}' already exists (id: {existing.id})",
                    short_name=short_name,
                    operator_id=existing.id,
                )

        operator_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # 3. Store the operator file on disk
        stored_filename = original_filename or operator_file_path.name
        self.file_store.store(
            operator_id=operator_id,
            operator_file_path=operator_file_path,
            stored_filename=stored_filename,
        )

        # 4. Create model and save metadata JSON
        operator = CustomOperator(
            id=operator_id,
            name=name.strip(),
            description=description.strip() if description else "",
            short_name=short_name,
            status=CustomOperatorStatus.VALIDATED,
            message="Operator validated and stored successfully",
            operator_file=stored_filename,
            created_at=now,
            updated_at=now,
            metadata={
                "category": validation_info["category"],
                "class_name": validation_info["class_name"],
            },
        )
        operator.validate()

        self.metadata_storage.save_record(
            collection=CUSTOM_OPERATORS_COLLECTION,
            key=operator_id,
            data=operator.to_dict(),
        )

        # 5. Refresh runtime operator factory
        self._refresh_operator_factories()

        return operator

    def get_operator(self, *, operator_id: str) -> CustomOperator:
        """Retrieve a custom operator by ID.

        Args:
            operator_id: UUID of the operator

        Returns:
            CustomOperator instance
        """
        self._validate_uuid(operator_id=operator_id)

        record = self.metadata_storage.get_record(
            collection=CUSTOM_OPERATORS_COLLECTION,
            key=operator_id,
        )
        if not record:
            raise CustomOperatorNotFoundException(
                message=f"Custom operator with id '{operator_id}' not found",
                operator_id=operator_id,
            )

        operator = CustomOperator.from_dict(data=record)

        # Verify file existence consistency
        op_dir = self.file_store.get_operator_dir(operator_id=operator_id)
        if not op_dir or not (op_dir / operator.operator_file).exists():
            operator.status = CustomOperatorStatus.INVALID
            operator.message = "operator file not found on disk"

        return operator

    def list_operators(self) -> list[CustomOperator]:
        """List all custom operators with disk consistency verification.

        Returns:
            List of CustomOperator domain models
        """
        records = self.metadata_storage.list_records(collection=CUSTOM_OPERATORS_COLLECTION)
        operators: list[CustomOperator] = []

        for record in records:
            try:
                op = CustomOperator.from_dict(data=record)
                if op.id:
                    op_dir = self.file_store.get_operator_dir(operator_id=op.id)
                    if not op_dir or not (op_dir / op.operator_file).exists():
                        op.status = CustomOperatorStatus.INVALID
                        op.message = "operator file not found on disk"
                operators.append(op)
            except Exception as e:
                logger.warning("Failed to parse custom operator record %s: %s", record.get("id"), e)

        return operators

    def update_operator(
        self,
        *,
        operator_id: str,
        name: str | None = None,
        description: str | None = None,
        operator_file_path: Path | None = None,
        original_filename: str | None = None,
    ) -> CustomOperator:
        """Update an existing custom operator (metadata-only or file replacement).

        Args:
            operator_id: UUID of the operator
            name: Optional updated name
            description: Optional updated description
            operator_file_path: Optional new .py file to replace existing
            original_filename: Original filename from the upload (used for storage and metadata).
                               Falls back to operator_file_path.name if not provided.

        Returns:
            Updated CustomOperator instance
        """
        self._validate_uuid(operator_id=operator_id)
        current = self.get_operator(operator_id=operator_id)

        now = datetime.now(UTC)
        updated_name = name.strip() if name is not None else current.name
        updated_description = description.strip() if description is not None else current.description

        if operator_file_path is None:
            # Metadata-only update
            # Verify backing file directory still exists
            op_dir = self.file_store.get_operator_dir(operator_id=operator_id)
            if not op_dir:
                raise CustomOperatorNotFoundException(
                    message=f"Operator directory for '{operator_id}' not found on disk",
                    operator_id=operator_id,
                )

            current.name = updated_name
            current.description = updated_description
            current.updated_at = now
            current.validate()

            self.metadata_storage.save_record(
                collection=CUSTOM_OPERATORS_COLLECTION,
                key=operator_id,
                data=current.to_dict(),
            )
            return current

        # File replacement update
        self._require_custom_operators_enabled()
        validation_info = validate_operator_file(operator_file_path=operator_file_path)
        new_short_name = validation_info["short_name"]

        if new_short_name != current.short_name:
            raise CustomOperatorInvalidDataException(
                message=(
                    f"Cannot change short_name from '{current.short_name}' to '{new_short_name}'. "
                    "Delete and re-create the operator to change short_name."
                ),
                field_name="short_name",
            )

        # Store replaced file
        stored_filename = original_filename or operator_file_path.name
        self.file_store.store(
            operator_id=operator_id,
            operator_file_path=operator_file_path,
            stored_filename=stored_filename,
        )

        current.name = updated_name
        current.description = updated_description
        current.operator_file = stored_filename
        current.status = CustomOperatorStatus.VALIDATED
        current.message = "Operator file updated and validated successfully"
        current.updated_at = now
        current.metadata = {
            "category": validation_info["category"],
            "class_name": validation_info["class_name"],
        }
        current.validate()

        self.metadata_storage.save_record(
            collection=CUSTOM_OPERATORS_COLLECTION,
            key=operator_id,
            data=current.to_dict(),
        )

        self._refresh_operator_factories()
        return current

    def delete_operator(self, *, operator_id: str) -> None:
        """Delete custom operator files and metadata.

        Args:
            operator_id: UUID of the operator
        """
        self._validate_uuid(operator_id=operator_id)

        # 1. Ensure operator exists
        record = self.metadata_storage.get_record(
            collection=CUSTOM_OPERATORS_COLLECTION,
            key=operator_id,
        )
        if not record:
            raise CustomOperatorNotFoundException(
                message=f"Custom operator with id '{operator_id}' not found",
                operator_id=operator_id,
            )

        # 2. Delete file directory first
        self.file_store.delete(operator_id=operator_id)

        # 3. Delete metadata JSON record
        self.metadata_storage.delete_record(
            collection=CUSTOM_OPERATORS_COLLECTION,
            key=operator_id,
        )

        # 4. Refresh operator factory
        self._refresh_operator_factories()

    def get_directory_tree(self, *, depth: int = 10) -> dict[str, Any]:
        """Return the custom operators directory tree.

        Args:
            depth: Maximum depth of directory traversal

        Returns:
            Dictionary structure of directory tree
        """
        return self.file_store.get_directory_tree(depth=depth)
