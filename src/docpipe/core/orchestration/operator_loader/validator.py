"""Operator validation logic for custom operators."""

import inspect
from types import ModuleType

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.operators.abstract_operator import AbstractOperator
from docpipe.core.orchestration.operator_loader.ports.operator_source import (
    OperatorInfo,
    ValidationResult,
)
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class OperatorValidator:
    """Validates custom operator implementations.

    Performs strict validation at discovery time to ensure custom operators
    meet all requirements before being loaded into the operator factory.
    """

    @staticmethod
    def _validate_required_methods(*, cls: type, errors: list[str]) -> None:
        """Validate that required methods are defined directly on the class and are callable."""
        for method_name in ["transform"]:
            if method_name not in cls.__dict__:
                errors.append(f"{cls.__name__} must implement '{method_name}' method")
            elif not callable(getattr(cls, method_name)):
                errors.append(f"{cls.__name__}.{method_name} must be callable")

    @staticmethod
    def _validate_optional_methods(*, cls: type, errors: list[str]) -> None:
        """Validate that optional inherited methods (get_metadata, get_required_features) are callable."""
        for method_name in ["get_metadata", "get_required_features"]:
            if not hasattr(cls, method_name):
                errors.append(f"{cls.__name__} must have '{method_name}' method")
            elif not callable(getattr(cls, method_name)):
                errors.append(f"{cls.__name__}.{method_name} must be callable")

    @staticmethod
    def validate_operator_class(*, cls: type, operator_info: OperatorInfo) -> ValidationResult:
        """Validate operator class structure and interface.

        Args:
            cls: The operator class to validate
            operator_info: Metadata about the operator

        Returns:
            ValidationResult with validation status and messages
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not inspect.isclass(cls):
            errors.append(f"{operator_info.name} is not a class")
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        if not issubclass(cls, AbstractOperator):
            errors.append(f"{cls.__name__} must inherit from AbstractOperator")

        # Check required class attributes
        if not hasattr(cls, "short_name"):
            errors.append(f"{cls.__name__} must define 'short_name' class attribute")
        elif not isinstance(cls.short_name, str) or not cls.short_name:
            errors.append(f"{cls.__name__}.short_name must be a non-empty string")

        if not hasattr(cls, "category"):
            errors.append(f"{cls.__name__} must define 'category' class attribute")

        # Check owner attribute - custom operators should not claim to be docpipe-owned
        owner = getattr(cls, DocpipeConstants.OWNER_ATTRIBUTE, None)
        if owner != DocpipeConstants.OWNER_CUSTOM:
            errors.append(
                f"{cls.__name__} has owner='{owner}'. "
                f"Custom operators should set owner='{DocpipeConstants.OWNER_CUSTOM}'"
            )

        OperatorValidator._validate_required_methods(cls=cls, errors=errors)
        OperatorValidator._validate_optional_methods(cls=cls, errors=errors)

        if not hasattr(cls, "__doc__") or not cls.__doc__:
            warnings.append(f"{cls.__name__} should have a docstring")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def validate_module(*, module: ModuleType, operator_info: OperatorInfo) -> ValidationResult:
        """Validate that module contains a valid operator class.

        Args:
            module: The loaded module to validate
            operator_info: Metadata about the expected operator

        Returns:
            ValidationResult with validation status and messages
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Find operator classes in module
        operator_classes = []
        for _, obj in inspect.getmembers(module):
            if (
                inspect.isclass(obj)
                and issubclass(obj, AbstractOperator)
                and obj is not AbstractOperator
                and obj.__module__ == module.__name__
            ):
                operator_classes.append(obj)

        if not operator_classes:
            errors.append(f"No operator classes found in module {operator_info.module_path}")
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        if len(operator_classes) > 1:
            warnings.append(
                f"Multiple operator classes found in {operator_info.module_path}. "
                f"Using first one: {operator_classes[0].__name__}"
            )

        # Validate the first operator class found
        operator_class = operator_classes[0]
        class_validation = OperatorValidator.validate_operator_class(cls=operator_class, operator_info=operator_info)

        return ValidationResult(
            valid=class_validation.valid,
            errors=errors + class_validation.errors,
            warnings=warnings + class_validation.warnings,
        )
