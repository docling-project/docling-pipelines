# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Port interface for operator source adapters.

This port defines the contract that all operator source adapters must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from types import ModuleType
from typing import Any


class TrustClass(StrEnum):
    """How much the platform trusts the code of an operator, decided by where it was loaded from.

    ``PLATFORM`` operators ship in-tree. ``DEPLOYER_INSTALLED`` operators come from a pip package or a path the
    deployer configured, and are trusted like platform code. ``UNTRUSTED`` operators were uploaded through the API or
    come from an object-store source; their code is never imported by the discovery path.
    """

    PLATFORM = "platform"
    DEPLOYER_INSTALLED = "deployer-installed"
    UNTRUSTED = "untrusted"


@dataclass
class OperatorInfo:
    """Metadata about a discovered operator.

    Attributes:
        name: Full class name of the operator
        short_name: Short identifier used in flow definitions
        module_path: Python module path where operator is defined
        category: Operator category (Extract, Ingest, etc.)
        source_location: Original location where operator was found
        trust_class: Trust class derived from the source the operator was found in
        source_file: Absolute path of the operator file; set for untrusted operators, which are described from it
            without importing it
        static_metadata: The statically known entries of ``get_metadata()`` (declared secret fields, label, features),
            read as literals from the source; untrusted operators only
    """

    name: str
    short_name: str
    module_path: str
    category: str
    source_location: str
    trust_class: TrustClass = TrustClass.DEPLOYER_INSTALLED
    source_file: str | None = None
    static_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of operator validation.

    Attributes:
        valid: Whether the operator passed validation
        errors: List of validation error messages
        warnings: List of validation warning messages
    """

    valid: bool
    errors: list[str]
    warnings: list[str]


class OperatorSourcePort(ABC):
    """Port interface for operator source adapters.

    This interface defines the contract for discovering and loading custom operators
    from various sources (filesystem, S3, etc.). Adapters implementing this port
    handle source-specific details while the loader service depends only on this
    abstraction.

    Attributes:
        ADAPTER_NAME: Unique identifier for the adapter (e.g., 'filesystem', 's3')
        ADAPTER_DISPLAY_NAME: Human-readable name for UI display
    """

    ADAPTER_NAME: str
    ADAPTER_DISPLAY_NAME: str

    @abstractmethod
    def list_operators(self) -> list[OperatorInfo]:
        """Discover and list all available operators from this source.

        Returns:
            List of OperatorInfo objects for discovered operators

        Raises:
            Exception: If discovery operation fails
        """
        ...

    def clear_cache(self):
        """Clear any cached modules to force reloading.

        Optional method for adapters that cache loaded modules.
        Called before refresh operations to ensure updated code is loaded.
        """

    @abstractmethod
    def load_operator(self, *, operator_info: OperatorInfo) -> ModuleType:
        """Load operator module from this source.

        Args:
            operator_info: Metadata about the operator to load

        Returns:
            Loaded Python module containing the operator class

        Raises:
            Exception: If loading operation fails
        """
        ...

    @abstractmethod
    def validate_operator(self, *, module: ModuleType, operator_info: OperatorInfo) -> ValidationResult:
        """Validate operator implementation.

        Args:
            module: Loaded operator module
            operator_info: Metadata about the operator

        Returns:
            ValidationResult with validation status and messages

        Raises:
            Exception: If validation check fails
        """
        ...
