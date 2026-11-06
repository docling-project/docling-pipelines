import os
import threading
from typing import ClassVar

from docpipe.core.constants.constants import DocpipeConstants, EnvironmentVariables, OrchestratorType
from docpipe.core.operators.abstract_operator import AbstractOperator
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class OperatorFactoryProvider:
    """Operatorfactoryprovider."""

    operator_factories: ClassVar[dict[str, "OperatorFactory"]] = {}

    @staticmethod
    def _resolve_factory_key(
        *, orchestrator: str, package_names: list[str] | None, enable_custom_operators: bool
    ) -> tuple[str, list[str]]:
        """Merge env packages into package_names and return the cache key and merged list."""
        env_packages = os.getenv(EnvironmentVariables.DOCPIPE_CUSTOM_OPERATORS, "")
        if env_packages:
            if not isinstance(env_packages, str):
                logger.warning(
                    "DOCPIPE_CUSTOM_OPERATORS must be a string, got %s. Ignoring environment variable.",
                    type(env_packages).__name__,
                )
            else:
                env_package_list = [pkg.strip() for pkg in env_packages.split(",") if pkg.strip()]
                package_names = (package_names or []) + env_package_list

        merged = package_names or []
        enable_flag = DocpipeConstants.FEATURE_ENABLED if enable_custom_operators else DocpipeConstants.FEATURE_DISABLED
        key = f"{orchestrator}_{enable_flag}_{'_'.join(merged)}"
        return key, merged

    @staticmethod
    def get_operator_factory(
        *, orchestrator: str, package_names: list[str] | None = None, enable_custom_operators: bool = True
    ) -> "OperatorFactory":
        """
        Get or create an operator factory with optional custom operator support.

        Parameters:
        - orchestrator: Type of orchestrator (e.g., "python")
        - package_names: Optional list of custom operator package paths
        - enable_custom_operators: Whether to enable custom operators (default: from env or True)

        Returns:
            OperatorFactory instance
        """
        key, package_names = OperatorFactoryProvider._resolve_factory_key(
            orchestrator=orchestrator,
            package_names=package_names,
            enable_custom_operators=enable_custom_operators,
        )
        logger.debug("operator_factory_key:%s", key)

        if key in OperatorFactoryProvider.operator_factories:
            return OperatorFactoryProvider.operator_factories[key]

        operator_factory = OperatorFactory(orchestrator, package_names, enable_custom_operators=enable_custom_operators)
        OperatorFactoryProvider.operator_factories[key] = operator_factory
        return operator_factory

    @staticmethod
    def refresh_operator_factory(
        *, orchestrator: str, package_names: list[str] | None = None, enable_custom_operators: bool = True
    ) -> "OperatorFactory":
        """
        Refreshes the operator factory by reloading custom operator classes dynamically.

        Parameters:
        - orchestrator: Type of orchestrator (e.g., "python")
        - package_names: Optional list of custom operator package paths
        - enable_custom_operators: Whether to enable custom operators

        Returns:
            OperatorFactory instance
        """
        key, package_names = OperatorFactoryProvider._resolve_factory_key(
            orchestrator=orchestrator,
            package_names=package_names,
            enable_custom_operators=enable_custom_operators,
        )
        logger.info("Refreshing operator factory: %s", key)

        if key in OperatorFactoryProvider.operator_factories:
            OperatorFactoryProvider.operator_factories[key].refresh_operators()
            return OperatorFactoryProvider.operator_factories[key]

        # If the factory does not exist, create a new one
        return OperatorFactoryProvider.get_operator_factory(
            orchestrator=orchestrator, package_names=package_names, enable_custom_operators=enable_custom_operators
        )


class OperatorFactory:
    """
    Factory class for loading operators from frozenset registry and custom packages.
    Supports priority-based operator resolution where lower number = higher priority.
    """

    def __init__(
        self,
        orchestrator: str,
        package_names: list[str] | None = None,
        enable_custom_operators: bool = True,
    ) -> None:
        """
        Initialize the factory with frozenset operators and optional custom packages.

        Parameters:
        - orchestrator: the operator classes for the given orchestrator will be loaded
        - package_names: list of module names for custom operators (optional)
        - enable_custom_operators: whether to load custom operators (default: from env or True)
        """
        self.orchestrator = orchestrator
        self.package_names = package_names or []
        self.operators: dict[str, type[AbstractOperator]] = {}
        self._lock = threading.Lock()

        # Determine if custom operators are enabled
        # Priority: parameter > environment variable > default
        if enable_custom_operators is None:  # pragma: no cover
            env_value = os.getenv(EnvironmentVariables.DOCPIPE_ENABLE_CUSTOM_OPERATORS)
            if env_value is not None:
                enable_custom_operators = env_value.lower() in ("true", "1", "yes")
            else:
                enable_custom_operators = DocpipeConstants.ENABLE_CUSTOM_OPERATORS_DEFAULT

        self.enable_custom_operators = enable_custom_operators

        # Always load OSS operators from frozenset
        self._load_operators_from_frozenset()

        # Load custom operators ONLY if enabled
        if self.enable_custom_operators and self.package_names:
            logger.info("Custom operators ENABLED - loading from packages")
            self._load_custom_operators_from_packages()
        elif not self.enable_custom_operators:
            logger.warning("Custom operators DISABLED - only docpipe operators will be available")
        else:
            logger.info("No custom operator packages specified")

    def _load_operators_from_frozenset(self):
        """
        Load operators from frozenset registry (OSS + external operators).

        Applies priority-based resolution to handle conflicts when multiple operators
        have the same short_name.
        """
        from docpipe.core.operators.operator_registry import get_docpipe_operators

        logger.info("Loading docpipe operators from frozenset for orchestrator: %s", self.orchestrator)

        # Get all operators from registry (may contain duplicates by short_name)
        all_operators = get_docpipe_operators(orchestrator=self.orchestrator)

        # Apply priority resolution and availability checks
        for operator_class in all_operators:
            try:
                # Check if operator is available in current environment
                if hasattr(operator_class, "is_available") and callable(operator_class.is_available):
                    if not operator_class.is_available():
                        short_name = getattr(operator_class, "short_name", operator_class.__name__)
                        logger.debug("Operator '%s' is not available in current environment, skipping", short_name)
                        continue

                # Apply priority-based resolution
                OperatorFactory.apply_priority_resolution(
                    new_operator=operator_class,
                    operators_dict=self.operators,
                    default_owner=DocpipeConstants.OWNER_DOCPIPE,
                    log_prefix="Operator",
                )
            except Exception as e:
                logger.exception("Error processing operator %s: %s", operator_class.__name__, e)

        logger.info(
            "Loaded %d operators from frozenset (docpipe + external, after priority resolution)",
            len(self.operators),
        )

    def _load_custom_operators_from_packages(self, *, clear_cache: bool = False) -> dict[str, type[AbstractOperator]]:
        """Load custom operators from all sources (packages, filesystem, S3) with priority resolution.

        Args:
            clear_cache: If True, clear adapter caches before loading (for refresh)

        Returns:
            Dictionary mapping operator short names to operator classes
        """
        if not self.enable_custom_operators:
            logger.warning("Attempted to load custom operators but feature is disabled")
            return {}

        logger.info("Loading custom operators from sources: %s", self.package_names)

        try:
            # Use CustomOperatorLoader for unified loading from all sources
            from docpipe.core.orchestration.operator_loader.loader_service import CustomOperatorLoader

            # Create loader with auto-detection of source types
            loader = CustomOperatorLoader.from_paths(self.package_names)

            # Load and validate operators
            custom_operators = loader.validate_and_load(builtin_operators=self.operators, clear_cache=clear_cache)

            # Apply priority resolution between docpipe and custom operators
            for _short_name, operator_class in custom_operators.items():
                OperatorFactory.apply_priority_resolution(
                    new_operator=operator_class,
                    operators_dict=self.operators,
                    default_owner=DocpipeConstants.OWNER_CUSTOM,
                    log_prefix="Custom operator",
                )

            logger.info("Successfully loaded %d custom operator(s)", len(custom_operators))
            return custom_operators

        except Exception as e:
            logger.exception("Failed to load custom operators: %s", e)
            return {}

    @staticmethod
    def register_owner_priority(*, owner: str, priority: int) -> None:
        """Register a custom owner tier and its resolution priority.

        Allows consumers to inject additional owner tiers at runtime without
        requiring changes to the docpipe library. Call this before operators are
        loaded.

        Lower priority numbers take precedence over higher numbers.
        Priorities 100 (OWNER_CUSTOM) and 200 (OWNER_DOCPIPE) are reserved.
        Use values below 100 to outrank all built-in tiers, or values between
        100 and 200 to slot between custom and docpipe operators.

        Args:
            owner: Owner string identifier (e.g. "my_app").
            priority: Integer priority. Lower number = higher precedence.
        """
        DocpipeConstants.OPERATOR_PRIORITY_MAP[owner] = priority

    @staticmethod
    def apply_priority_resolution(
        *,
        new_operator: type[AbstractOperator],
        operators_dict: dict[str, type[AbstractOperator]],
        default_owner: str = DocpipeConstants.OWNER_DOCPIPE,
        log_prefix: str = "Operator",
    ) -> bool:
        """
        Apply priority-based resolution to add or reject an operator.

        This function checks if a new operator should be added to the operators dictionary,
        potentially overriding an existing operator with the same short_name based on
        ownership priority.

        Args:
            new_operator: The operator class to add
            operators_dict: Dictionary of existing operators (short_name -> class)
            default_owner: Default owner if operator doesn't have owner attribute
            log_prefix: Prefix for log messages (e.g., "Operator", "Custom operator")

        Returns:
            bool: True if operator was added/updated, False if rejected

        Side Effects:
            - May update operators_dict if operator is added or overrides existing
            - Logs info/warning messages about resolution decisions
        """
        if not hasattr(new_operator, "short_name"):
            logger.warning("%s %s missing 'short_name' attribute, skipping", log_prefix, new_operator.__name__)
            return False

        short_name = new_operator.short_name
        existing_operator = operators_dict.get(short_name)

        should_override, new_priority, existing_priority = OperatorFactory.resolve_operator_by_priority(
            new_operator=new_operator,
            existing_operator=existing_operator,
            default_owner=default_owner,
        )

        if existing_operator is None:
            # No conflict, add the operator
            operators_dict[short_name] = new_operator
            logger.debug("Added %s: %s", log_prefix.lower(), short_name)
            return True

        if should_override:
            logger.info(
                "%s '%s': %s (priority=%s) overrides %s (priority=%s)",
                log_prefix,
                short_name,
                new_operator.__name__,
                new_priority,
                existing_operator.__name__,
                existing_priority,
            )
            operators_dict[short_name] = new_operator
            return True
        logger.info(
            "%s '%s': %s (priority=%s) cannot override %s (priority=%s)",
            log_prefix,
            short_name,
            new_operator.__name__,
            new_priority,
            existing_operator.__name__,
            existing_priority,
        )
        return False

    @staticmethod
    def resolve_operator_by_priority(
        new_operator: type[AbstractOperator],
        existing_operator: type[AbstractOperator] | None,
        default_owner: str = DocpipeConstants.OWNER_DOCPIPE,
    ) -> tuple[bool, int | float, int | float]:
        """
        Determine if a new operator should override an existing one based on priority.

        Priority rules (lower number = higher priority):
        - Enterprise operators (0) can override Custom (1) and OSS (2)
        - Custom operators (1) can override OSS (2) but not Enterprise (0)
        - OSS operators (2) cannot override Custom (1) or Enterprise (0)

        Args:
            new_operator: The new operator class to potentially add
            existing_operator: The existing operator class (None if no conflict)
            default_owner: Default owner if operator doesn't have owner attribute

        Returns:
            Tuple of (should_override: bool, new_priority: int, existing_priority: int)
            If existing_operator is None, returns (True, new_priority, inf)
        """
        # Get new operator's priority
        new_owner = getattr(new_operator, DocpipeConstants.OWNER_ATTRIBUTE, None) or default_owner
        new_priority = DocpipeConstants.OPERATOR_PRIORITY_MAP.get(new_owner, float("inf"))

        # If no existing operator, always add the new one
        if existing_operator is None:
            return True, new_priority, float("inf")

        # Get existing operator's priority
        existing_owner = getattr(existing_operator, DocpipeConstants.OWNER_ATTRIBUTE, None) or default_owner
        existing_priority = DocpipeConstants.OPERATOR_PRIORITY_MAP.get(existing_owner, float("inf"))

        # Lower or equal priority value means higher precedence
        should_override = new_priority <= existing_priority

        return should_override, new_priority, existing_priority

    def refresh_operators(self) -> None:
        """Refreshes custom operators (non-core packages) with priority resolution."""
        if not self.enable_custom_operators:
            logger.warning("Cannot refresh operators: custom operators are disabled")
            return

        with self._lock:
            logger.info("Refreshing custom operators for: %s", self.orchestrator)

            # Clean reset of the custom operator slice before reloading
            custom_keys = [
                short_name
                for short_name, op_cls in self.operators.items()
                if getattr(op_cls, DocpipeConstants.OWNER_ATTRIBUTE, None) == DocpipeConstants.OWNER_CUSTOM
            ]
            for short_name in custom_keys:
                del self.operators[short_name]

            # Use CustomOperatorLoader to reload operators from packages with cache clearing
            try:
                self._load_custom_operators_from_packages(clear_cache=True)
            except Exception as e:
                logger.error("Failed to refresh custom operators: %s", e)
                raise

    def get_operator(self, *, operator_name: str) -> type[AbstractOperator] | None:
        """Get operator."""
        return self.operators.get(operator_name)


def main():  # pragma: no cover
    """
    main entry point into the program; used for unit testing only
    """
    factory = OperatorFactoryProvider.get_operator_factory(orchestrator=OrchestratorType.PYTHON)
    logger.info("Loaded %d operators", len(factory.operators))

    for key, value in factory.operators.items():
        logger.debug(" short_name: %s ==> class_name: %s", key, value.__name__)


# main entry point into the program; used for unit testing only
if __name__ == "__main__":  # pragma: no cover
    main()
