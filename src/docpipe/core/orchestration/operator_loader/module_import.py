# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Import a Python file as a module. This executes the file's top-level code."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def import_module_from_file(*, file_path: Path) -> ModuleType:
    """Load a Python module from a file path by executing it.

    Only call this for code the platform trusts (platform and deployer-installed sources), or from inside the
    isolation boundary for untrusted code. Discovery and validation of untrusted operators must not call it.

    Args:
        file_path: Path to the Python file

    Returns:
        The executed module

    Raises:
        ImportError: If the module spec cannot be built or executing the module fails
    """
    # Generate unique module name based on file path
    module_name = f"custom_operator_{file_path.stem}_{hash(str(file_path))}"

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec from {file_path}")

    module = importlib.util.module_from_spec(spec)

    # Add to sys.modules temporarily for imports to work
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception as e:
        # Clean up on failure
        sys.modules.pop(module_name, None)
        raise ImportError(f"Failed to execute module {file_path}: {e}") from e

    return module
