"""Custom operator loader service.

This service coordinates the discovery and loading of custom operators from
multiple sources.
"""

from typing import Any

from docpipe.core.operators.abstract_operator import AbstractOperator
from docpipe.core.orchestration.operator_loader.adapters.factories.operator_source_factory import (
    OperatorSourceFactory,
)
from docpipe.core.orchestration.operator_loader.ports.operator_source import (
    OperatorInfo,
    OperatorSourcePort,
)
from docpipe.core.orchestration.operator_loader.validator import OperatorValidator
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class CustomOperatorLoader:
    """Service for loading custom operators from multiple sources.

    This service coordinates operator discovery, validation, and loading
    from various sources (filesystem directories, S3 buckets, Python packages)
    while handling conflicts and ensuring operator quality.

    Supported sources:
    - Filesystem: Local directories or files containing operators
    - S3: Amazon S3 buckets with operator files
    - Package: Pip-installed Python packages with operators
    """

    def __init__(self, sources: list[OperatorSourcePort]):
        """Initialize the loader with operator sources.

        Args:
            sources: List of operator source adapters to use
        """
        self.sources = sources
        self.loaded_operators: dict[str, type[AbstractOperator]] = {}

    @classmethod
    def from_source_configs(cls, source_configs: list[dict[str, Any]]) -> "CustomOperatorLoader":
        """Create loader from source configuration dictionaries.

        Args:
            source_configs: List of source configurations, each containing:
                - adapter_name: Name of the adapter to use
                - **kwargs: Adapter-specific configuration

        Returns:
            Initialized CustomOperatorLoader instance

        Example:
            configs = [
                {"adapter_name": "filesystem", "path": "/path/to/operators"},
                {"adapter_name": "s3", "bucket": "my-bucket", "prefix": "operators/"}
            ]
            loader = CustomOperatorLoader.from_source_configs(configs)
        """
        sources = []
        for config in source_configs:
            adapter_name = config.pop("adapter_name")
            source = OperatorSourceFactory.create(adapter_name, **config)
            sources.append(source)

        return cls(sources)

    @classmethod
    def from_paths(cls, paths: list[str]) -> "CustomOperatorLoader":
        """Create loader from path strings (auto-detect adapter type).

        Args:
            paths: List of paths (local filesystem paths or S3 URIs)

        Returns:
            Initialized CustomOperatorLoader instance

        Example:
            paths = ["/local/path", "s3://bucket/path"]
            loader = CustomOperatorLoader.from_paths(paths)
        """
        from pathlib import Path

        sources = []
        for path in paths:
            if path.startswith("s3://"):
                # S3 URI
                source = OperatorSourceFactory.create("s3", uri=path)
                sources.append(source)
            elif Path(path).is_absolute() or Path(path).exists() or "/" in path or "\\" in path:
                # Local filesystem path (absolute, exists, or contains path separators)
                source = OperatorSourceFactory.create("filesystem", path=path)
                sources.append(source)
            else:
                # Treat as Python package name
                try:
                    source = OperatorSourceFactory.create("package", package_name=path)
                    sources.append(source)
                except ImportError:
                    logger.warning(
                        "Skipping path '%s': not a valid filesystem path, S3 URI, or installed package", path
                    )

        return cls(sources)

    def discover_operators(
        self, *, clear_cache: bool = False
    ) -> tuple[dict[str, OperatorInfo], dict[str, OperatorSourcePort]]:
        """Discover operators from all sources.

        Args:
            clear_cache: If True, clear adapter caches before discovering (for refresh)

        Returns:
            Tuple containing:
            - Dictionary mapping short_name to OperatorInfo
            - Dictionary mapping source_location to OperatorSourcePort

        Note:
            If multiple sources provide operators with the same short_name,
            the first one discovered is used.
        """
        discovered: dict[str, OperatorInfo] = {}
        source_map: dict[str, OperatorSourcePort] = {}

        # Clear caches if requested (for refresh operations)
        if clear_cache:
            for source in self.sources:
                source.clear_cache()

        for source in self.sources:
            try:
                operators = source.list_operators()
                logger.info("Discovered %s operators from %s", len(operators), source.ADAPTER_DISPLAY_NAME)

                for op_info in operators:
                    if op_info.short_name in discovered:
                        logger.warning(
                            "Operator '%s' already discovered from %s. Skipping duplicate from %s",
                            op_info.short_name,
                            discovered[op_info.short_name].source_location,
                            op_info.source_location,
                        )
                        continue

                    discovered[op_info.short_name] = op_info
                    source_map[op_info.source_location] = source

            except Exception as e:
                logger.exception("Failed to discover operators from %s: %s", source.ADAPTER_DISPLAY_NAME, e)

        return discovered, source_map

    def load_and_validate_operator(
        self,
        op_info: OperatorInfo,
        source: OperatorSourcePort,
    ) -> type[AbstractOperator] | None:
        """Load and validate a single operator.

        Args:
            op_info: Operator metadata
            source: Source adapter to load from

        Returns:
            Loaded operator class if valid, None otherwise
        """
        try:
            # Load the module
            module = source.load_operator(operator_info=op_info)

            # Validate the module
            validation_result = source.validate_operator(module=module, operator_info=op_info)

            # Log warnings
            for warning in validation_result.warnings:
                logger.warning("Operator '%s': %s", op_info.short_name, warning)

            # Check for errors
            if not validation_result.valid:
                for error in validation_result.errors:
                    logger.error("Operator '%s': %s", op_info.short_name, error)
                return None

            # Extract operator class from module
            operator_class = self._extract_operator_class(module, op_info)
            if operator_class is None:
                logger.error("Could not extract operator class from module %s", op_info.module_path)
                return None

            return operator_class

        except Exception as e:
            logger.exception("Failed to load operator '%s' from %s: %s", op_info.short_name, op_info.source_location, e)
            return None

    def _extract_operator_class(
        self,
        module: Any,
        op_info: OperatorInfo,
    ) -> type[AbstractOperator] | None:
        """Extract operator class from loaded module.

        Args:
            module: Loaded Python module
            op_info: Operator metadata

        Returns:
            Operator class if found, None otherwise
        """
        return OperatorValidator.select_operator_class(module=module, operator_info=op_info)

    def validate_and_load(
        self,
        builtin_operators: dict[str, type[AbstractOperator]],
        *,
        clear_cache: bool = False,
    ) -> dict[str, type[AbstractOperator]]:
        """Discover, validate, and load all custom operators.

        Args:
            builtin_operators: Dictionary of built-in operators (for conflict detection)
            clear_cache: If True, clear adapter caches before loading (for refresh)

        Returns:
            Dictionary of successfully loaded custom operators (short_name -> class)
        """
        # Discover operators from all sources
        discovered, source_map = self.discover_operators(clear_cache=clear_cache)

        if not discovered:
            logger.info("No custom operators discovered")
            return {}

        logger.info("Discovered %s custom operators", len(discovered))

        # Load and validate each operator
        loaded: dict[str, type[AbstractOperator]] = {}

        # discover_operators() already keeps one operator per short_name, so the keys are unique.
        for short_name, op_info in discovered.items():
            # Get the source that provided this operator from the mapping
            source = source_map.get(op_info.source_location)

            if source is None:
                logger.error(
                    "Could not find source for operator '%s' with source_location '%s'",
                    short_name,
                    op_info.source_location,
                )
                continue

            # Load and validate the operator
            operator_class = self.load_and_validate_operator(op_info, source)

            if operator_class is not None:
                loaded[short_name] = operator_class
                logger.info(
                    "Successfully loaded custom operator: %s (%s) from %s",
                    short_name,
                    operator_class.__name__,
                    op_info.source_location,
                )

        self.loaded_operators = loaded
        logger.info("Loaded %s custom operators successfully", len(loaded))

        return loaded
