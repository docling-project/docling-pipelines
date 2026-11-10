# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Utility to manage temporary credential files safely (task C.4)."""

import json
import os
import shutil
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@contextmanager
def temporary_credential_file(
    content: str | bytes | dict[str, Any],
    *,
    suffix: str = ".json",
) -> Generator[Path, None, None]:
    """Create a temporary credential file with owner-only permissions (0600).

    The file is created in a private temporary directory and deleted on exit.

    Args:
        content: The credential string, bytes, or dict to write.
        suffix: Optional file suffix. Defaults to ".json".

    Yields:
        The Path to the created credential file.
    """
    temp_dir = tempfile.mkdtemp(prefix="docpipe-creds-")
    try:
        # Set directory permissions to 0700 (owner-only)
        Path(temp_dir).chmod(0o700)

        file_path = Path(temp_dir) / f"credentials{suffix}"

        if isinstance(content, dict):
            data = json.dumps(content).encode("utf-8")
        elif isinstance(content, str):
            data = content.encode("utf-8")
        else:
            data = content

        # Create file with 0600 permissions (owner-only read/write)
        fd = os.open(str(file_path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise

        yield file_path
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
