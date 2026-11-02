"""Package adapter for loading custom operators from installed Python packages."""

import importlib
import importlib.metadata
import inspect
import re
import sys
from types import ModuleType

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator
from docpipe.core.orchestration.operator_loader.adapters.factories.operator_source_factory import (
    register_operator_source,
)
from docpipe.core.orchestration.operator_loader.ports.operator_source import (
    OperatorInfo,
    OperatorSourcePort,
    ValidationResult,
)
from docpipe.core.orchestration.operator_loader.validator import OperatorValidator
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


@register_operator_source
class PackageAdapter(OperatorSourcePort):
    """Adapter for loading operators from installed Python packages.

    Discovers and loads operators from pip-installed packages, supporting both
    explicit module paths and entry point discovery.

    Attributes:
        ADAPTER_NAME: Unique identifier for this adapter
        ADAPTER_DISPLAY_NAME: Human-readable name
    """

    ADAPTER_NAME = "package"
    ADAPTER_DISPLAY_NAME = "Python Package"

    def __init__(self, *, package_name: str, operator_module: str = "operators"):
        """Initialize package adapter.

        Args:
            package_name: Name of the installed package (e.g., 'my_custom_operators')
            operator_module: Module path within package containing operators (default: 'operators')

        Raises:
            ImportError: If package is not installed
            ValueError: If package_name contains invalid characters or operator module cannot be found
        """
        # Validate package_name to prevent malicious characters
        self._validate_package_name(package_name)

        self.package_name = package_name
        self.operator_module = operator_module
        self._loaded_modules: dict[str, ModuleType] = {}

        # Verify package is installed
        try:
            importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ImportError(
                f"Package '{package_name}' is not installed. Install it with: pip install {package_name}"
            ) from exc

        # Verify package can be imported
        try:
            importlib.import_module(package_name)
        except ImportError as exc:
            raise ImportError(f"Failed to import package '{package_name}': {exc}") from exc

        # Construct full module path
        self.full_module_path = f"{package_name}.{operator_module}"

        # Verify operator module exists
        try:
            importlib.import_module(self.full_module_path)
        except ImportError as exc:
            raise ValueError(
                f"Operator module '{operator_module}' not found in package '{package_name}'. "
                f"Expected module path: {self.full_module_path}"
            ) from exc

        logger.info(
            "Initialized package adapter for package: %s, operator module: %s", package_name, self.full_module_path
        )

    def clear_cache(self):
        """Clear the module cache to force reloading of operators."""
        # Remove cached modules from sys.modules
        for module_path in list(self._loaded_modules.keys()):
            module = self._loaded_modules[module_path]
            if module.__name__ in sys.modules:
                del sys.modules[module.__name__]

        # Clear internal cache
        self._loaded_modules.clear()
        logger.debug("Cleared module cache for package %s", self.package_name)

    def list_operators(self) -> list[OperatorInfo]:
        """Discover all operators in the package.

        Discovers operators through two methods:
        1. Entry points registered under 'docpipe.operators'
        2. Direct module inspection of the operator_module

        Returns:
            List of OperatorInfo for discovered operators
        """
        operators: list[OperatorInfo] = []
        discovered_names: set[str] = set()

        # Method 1: Discover via entry points
        operators_from_entry_points = self._discover_via_entry_points()
        for op_info in operators_from_entry_points:
            if op_info.short_name not in discovered_names:
                operators.append(op_info)
                discovered_names.add(op_info.short_name)
                logger.debug("Discovered operator via entry point: %s", op_info.short_name)

        # Method 2: Discover via module inspection
        operators_from_module = self._discover_via_module_inspection()
        for op_info in operators_from_module:
            if op_info.short_name not in discovered_names:
                operators.append(op_info)
                discovered_names.add(op_info.short_name)
                logger.debug("Discovered operator via module inspection: %s", op_info.short_name)

        logger.info("Discovered %s operators from package %s", len(operators), self.package_name)
        return operators

    def _discover_via_entry_points(self) -> list[OperatorInfo]:
        """Discover operators via package entry points.

        Looks for entry points registered under 'docpipe.operators' group.

        Returns:
            List of OperatorInfo for operators found via entry points
        """
        operators: list[OperatorInfo] = []

        try:
            # Get entry points for docpipe.operators group (Python 3.10+ API)
            docpipe_operators = importlib.metadata.entry_points(group="docpipe.operators")

            for entry_point in docpipe_operators:
                # Only process entry points from our package
                if not entry_point.value.startswith(self.package_name):
                    continue

                try:
                    # Load the operator class
                    operator_class = entry_point.load()

                    if not (
                        inspect.isclass(operator_class)
                        and issubclass(operator_class, AbstractOperator)
                        and operator_class is not AbstractOperator
                    ):
                        logger.warning("Entry point '%s' does not reference a valid operator class", entry_point.name)
                        continue

                    if hasattr(operator_class, OperatorConstants.Misc.SHORT_NAME):
                        op_info = OperatorInfo(
                            name=operator_class.__name__,
                            short_name=getattr(operator_class, OperatorConstants.Misc.SHORT_NAME),
                            module_path=entry_point.value,
                            category=str(getattr(operator_class, OperatorConstants.Misc.CATEGORY)),
                            source_location=f"{self.ADAPTER_NAME}:{self.package_name}",
                        )
                        operators.append(op_info)

                except Exception as e:
                    logger.warning("Failed to load entry point '%s': %s", entry_point.name, e)

        except Exception as e:
            logger.warning("Failed to discover operators via entry points: %s", e)

        return operators

    def _discover_via_module_inspection(self) -> list[OperatorInfo]:
        """Discover operators by inspecting the operator module.

        Returns:
            List of OperatorInfo for operators found in the module
        """
        operators: list[OperatorInfo] = []

        try:
            # Import the operator module
            module = importlib.import_module(self.full_module_path)

            # Find operator classes in module
            operator_classes = OperatorValidator.find_operator_classes(module=module)

            for op_class in operator_classes:
                if hasattr(op_class, OperatorConstants.Misc.SHORT_NAME):
                    class_attribute = op_class.__name__
                    if vars(module).get(class_attribute) is not op_class:
                        matched_attribute = next((name for name, obj in vars(module).items() if obj is op_class), None)
                        if matched_attribute is None:
                            logger.warning("Operator class %s has no module attribute", op_class.__name__)
                            continue
                        class_attribute = matched_attribute
                    op_info = OperatorInfo(
                        name=op_class.__name__,
                        short_name=getattr(op_class, OperatorConstants.Misc.SHORT_NAME),
                        module_path=f"{self.full_module_path}:{class_attribute}",
                        category=str(getattr(op_class, OperatorConstants.Misc.CATEGORY)),
                        source_location=f"{self.ADAPTER_NAME}:{self.package_name}",
                    )
                    operators.append(op_info)

        except Exception as e:
            logger.warning("Failed to inspect module %s: %s", self.full_module_path, e)

        return operators

    def load_operator(self, *, operator_info: OperatorInfo) -> ModuleType:
        """Load operator module from package.

        Args:
            operator_info: Metadata about the operator to load

        Returns:
            Loaded Python module

        Raises:
            ImportError: If module loading fails
        """
        # Entry point paths include a class name, but the cache stores modules.
        module_path = operator_info.module_path.split(":", 1)[0]

        # Check if already loaded
        if module_path in self._loaded_modules:
            logger.debug("Using cached module for %s", operator_info.short_name)
            return self._loaded_modules[module_path]

        # Load the module
        try:
            module = importlib.import_module(module_path)
            self._loaded_modules[module_path] = module
            return module

        except ImportError as e:
            raise ImportError(
                f"Failed to load operator module '{module_path}' from package '{self.package_name}': {e}"
            ) from e

    def validate_operator(self, *, module: ModuleType, operator_info: OperatorInfo) -> ValidationResult:
        """Validate operator implementation.

        Args:
            module: Loaded operator module
            operator_info: Metadata about the operator

        Returns:
            ValidationResult with validation status and messages
        """
        return OperatorValidator.validate_module(module=module, operator_info=operator_info)

    @staticmethod
    def _validate_package_name(package_name: str) -> None:
        """Validate package name contains only safe characters.

        Python package names should only contain alphanumeric characters, underscores,
        hyphens, and dots (for namespace packages). This prevents injection attacks
        and ensures compatibility with Python's import system.

        Args:
            package_name: Package name to validate

        Raises:
            ValueError: If package_name is empty, not a string, or contains invalid characters
        """
        if not package_name or not isinstance(package_name, str):
            raise ValueError("package_name must be a non-empty string")

        # Check for path traversal attempts
        if ".." in package_name or "/" in package_name or "\\" in package_name:
            raise ValueError(
                f"Invalid package_name: {package_name}. "
                "Package names cannot contain path traversal characters (.., /, \\)"
            )

        # Valid Python package name pattern: alphanumeric, underscore, hyphen, and dot
        # Pattern allows namespace packages like 'my_company.my_package'
        # Each part must be a valid Python identifier (start with letter/underscore)
        parts = package_name.split(".")
        for part in parts:
            if not part:
                raise ValueError(
                    f"Invalid package_name: {package_name}. Package name cannot have empty parts (consecutive dots)"
                )
            # Allow alphanumeric, underscore, and hyphen; must start with letter or underscore
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_\-]*$", part):
                raise ValueError(
                    f"Invalid package_name: {package_name}. "
                    f"Part '{part}' contains invalid characters. "
                    "Each part must start with a letter or underscore and contain only "
                    "alphanumeric characters, underscores, and hyphens. "
                    "Examples: 'my_package', 'my-package', 'my_company.my_package'"
                )
