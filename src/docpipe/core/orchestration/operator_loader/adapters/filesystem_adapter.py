# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Filesystem adapter for loading custom operators from local directories."""

import inspect
from pathlib import Path
from types import ModuleType

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.custom_operators.validation import describe_operator_file
from docpipe.core.operators.abstract_operator import AbstractOperator
from docpipe.core.orchestration.operator_loader.adapters.factories.operator_source_factory import (
    register_operator_source,
)
from docpipe.core.orchestration.operator_loader.module_import import import_module_from_file
from docpipe.core.orchestration.operator_loader.ports.operator_source import (
    OperatorInfo,
    OperatorSourcePort,
    TrustClass,
    ValidationResult,
)
from docpipe.core.orchestration.operator_loader.validator import OperatorValidator
from docpipe.utils.infrastructure.filesystem import get_data_path
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


def classify_filesystem_path(*, path: Path) -> TrustClass:
    """Return the trust class of a filesystem operator path.

    The directory the API stores uploaded operators in is untrusted. Any other path was configured by the deployer.
    """
    upload_store = Path(get_data_path(sub_dir="/custom_operators")).resolve()
    if path.resolve().is_relative_to(upload_store):
        return TrustClass.UNTRUSTED
    return TrustClass.DEPLOYER_INSTALLED


@register_operator_source
class FilesystemAdapter(OperatorSourcePort):
    """Adapter for loading operators from local filesystem.

    Scans specified directory or file for Python files containing operator classes
    and loads them dynamically.

    Attributes:
        ADAPTER_NAME: Unique identifier for this adapter
        ADAPTER_DISPLAY_NAME: Human-readable name
    """

    ADAPTER_NAME = "filesystem"
    ADAPTER_DISPLAY_NAME = "Local Filesystem"

    def __init__(self, path: str, trust_class: TrustClass | None = None):
        """Initialize filesystem adapter.

        Args:
            path: Path to directory or Python file containing custom operators
            trust_class: Trust class of the operators under ``path``. Derived from the path when omitted: the API's
                upload store is untrusted, any other path is deployer-installed.
        """
        self.path = Path(path).resolve()
        self._loaded_modules: dict[str, ModuleType] = {}
        self._is_single_file = False

        if not self.path.exists():
            raise ValueError(f"Operator path does not exist: {self.path}")

        if self.path.is_file():
            if not self.path.suffix == ".py":
                raise ValueError(f"File must be a Python file (.py): {self.path}")
            self._is_single_file = True
            logger.info("Initialized filesystem adapter for file: %s", self.path)
        elif self.path.is_dir():
            logger.info("Initialized filesystem adapter for directory: %s", self.path)
        else:
            raise ValueError(f"Path must be a file or directory: {self.path}")

        self.trust_class = trust_class or classify_filesystem_path(path=self.path)

    def clear_cache(self):
        """Clear the module cache to force reloading of operators."""
        import sys

        # Remove cached modules from sys.modules
        for module_path in list(self._loaded_modules.keys()):
            module = self._loaded_modules[module_path]
            if module.__name__ in sys.modules:
                del sys.modules[module.__name__]

        # Clear internal cache
        self._loaded_modules.clear()
        logger.debug("Cleared module cache for %s", self.path)

    def list_operators(self) -> list[OperatorInfo]:
        """Discover all operators in the filesystem path.

        Returns:
            List of OperatorInfo for discovered operators
        """
        operators: list[OperatorInfo] = []

        if self._is_single_file:
            # Handle single file
            operators.extend(self._discover_operators_in_file(py_file=self.path))
        else:
            # Recursively scan directory for Python files
            for py_file in self.path.rglob("*.py"):
                # Skip __init__.py and private files
                if py_file.name.startswith("_"):
                    continue

                operators.extend(self._discover_operators_in_file(py_file=py_file))

        return operators

    def _discover_operators_in_file(self, *, py_file: Path) -> list[OperatorInfo]:
        """Discover operators in a single Python file.

        Args:
            py_file: Path to Python file

        Returns:
            List of OperatorInfo for operators found in the file
        """
        operators: list[OperatorInfo] = []

        # Determine relative path for module_path
        module_path = py_file.name if self._is_single_file else str(py_file.relative_to(self.path))

        try:
            if self.trust_class == TrustClass.UNTRUSTED:
                # Never import untrusted code: describe it from its AST
                operators.append(self._describe_untrusted_file(py_file=py_file, module_path=module_path))
                return operators

            # Load module to inspect it
            module = self._load_module_from_file(file_path=py_file)

            # Find operator classes in module
            operator_classes = self._find_operator_classes(module=module)

            for op_class in operator_classes:
                if hasattr(op_class, OperatorConstants.Misc.SHORT_NAME):
                    op_info = OperatorInfo(
                        name=op_class.__name__,
                        short_name=getattr(op_class, OperatorConstants.Misc.SHORT_NAME),
                        module_path=module_path,
                        category=str(getattr(op_class, OperatorConstants.Misc.CATEGORY)),
                        source_location=f"{self.ADAPTER_NAME}:{self.path}",
                        trust_class=self.trust_class,
                    )
                    operators.append(op_info)
                    logger.debug("Discovered operator: %s in %s", op_info.short_name, py_file)

        except Exception as e:
            logger.warning("Failed to inspect file %s: %s", py_file, e)

        return operators

    def _describe_untrusted_file(self, *, py_file: Path, module_path: str) -> OperatorInfo:
        """Build the operator info of an untrusted file from its AST, without importing it."""
        described = describe_operator_file(operator_file_path=py_file)
        op_info = OperatorInfo(
            name=described["class_name"],
            short_name=described["short_name"],
            module_path=module_path,
            category=described["category"],
            source_location=f"{self.ADAPTER_NAME}:{self.path}",
            trust_class=TrustClass.UNTRUSTED,
            source_file=str(py_file),
            static_metadata=described["metadata"],
        )
        logger.debug("Described untrusted operator: %s in %s", op_info.short_name, py_file)
        return op_info

    def load_operator(self, *, operator_info: OperatorInfo) -> ModuleType:
        """Load operator module from filesystem.

        Args:
            operator_info: Metadata about the operator to load

        Returns:
            Loaded Python module

        Raises:
            Exception: If module loading fails
            PermissionError: If this adapter's operators are untrusted, which are never imported here
        """
        if self.trust_class == TrustClass.UNTRUSTED:
            raise PermissionError(f"Refusing to import untrusted operator '{operator_info.short_name}'")

        # Construct full path to module file
        if self._is_single_file:
            module_file = self.path
        else:
            module_file = self.path / operator_info.module_path

        if not module_file.exists():
            raise FileNotFoundError(f"Operator file not found: {module_file}")

        # Check if already loaded
        cache_key = str(module_file)
        if cache_key in self._loaded_modules:
            logger.debug("Using cached module for %s", operator_info.short_name)
            return self._loaded_modules[cache_key]

        # Load the module
        module = self._load_module_from_file(file_path=module_file)
        self._loaded_modules[cache_key] = module

        return module

    def validate_operator(self, *, module: ModuleType, operator_info: OperatorInfo) -> ValidationResult:
        """Validate operator implementation.

        Args:
            module: Loaded operator module
            operator_info: Metadata about the operator

        Returns:
            ValidationResult with validation status and messages
        """
        return OperatorValidator.validate_module(module=module, operator_info=operator_info)

    def _load_module_from_file(self, *, file_path: Path) -> ModuleType:
        """Load a Python module from a file path by executing it.

        Args:
            file_path: Path to Python file

        Returns:
            Loaded module

        Raises:
            PermissionError: If this adapter's operators are untrusted, which are never executed here
            Exception: If module loading fails
        """
        if self.trust_class == TrustClass.UNTRUSTED:
            raise PermissionError(f"Refusing to execute untrusted operator file {file_path}")
        return import_module_from_file(file_path=file_path)

    def _find_operator_classes(self, *, module: ModuleType) -> list[type[AbstractOperator]]:
        """Find all operator classes in a module.

        Args:
            module: Module to inspect

        Returns:
            List of operator classes found
        """
        operators: list[type[AbstractOperator]] = []

        for _, obj in inspect.getmembers(module):
            if (
                inspect.isclass(obj)
                and issubclass(obj, AbstractOperator)
                and obj is not AbstractOperator
                and obj.__module__ == module.__name__
            ):
                operators.append(obj)

        return operators
