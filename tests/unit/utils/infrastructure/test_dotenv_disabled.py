# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for the ``PYTHON_DOTENV_DISABLED`` switch used by ``config.py``.

``config.py`` calls ``load_dotenv()`` at module level.  ``build_worker_environment``
sets ``PYTHON_DOTENV_DISABLED=1`` unconditionally so the worker's import of that
module does not populate the worker environment from a discoverable ``.env`` file.
These tests confirm the ``python-dotenv`` switch works as the implementation
relies on it, without re-importing the already-loaded module.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv


class TestDotenvDisabledSwitch:
    """``PYTHON_DOTENV_DISABLED`` controls whether ``load_dotenv()`` reads a file."""

    CANARY_NAME = "SYNTHETIC_DOTENV_CANARY"
    CANARY_VALUE = "dotenv-canary-value-cfg"  # pragma: allowlist secret

    @pytest.fixture(autouse=True)
    def _isolate_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(self.CANARY_NAME, raising=False)
        monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)

    def test_dotenv_loads_file_without_the_switch(self, *, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(f"{self.CANARY_NAME}={self.CANARY_VALUE}\n", encoding="utf-8")

        load_dotenv(dotenv_path=env_file)

        assert os.environ.get(self.CANARY_NAME) == self.CANARY_VALUE

    def test_dotenv_does_not_override_an_existing_variable(
        self, *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(self.CANARY_NAME, "existing-value")
        env_file = tmp_path / ".env"
        env_file.write_text(f"{self.CANARY_NAME}=new-value-from-file\n", encoding="utf-8")

        load_dotenv(dotenv_path=env_file)

        assert os.environ[self.CANARY_NAME] == "existing-value"

    def test_dotenv_is_not_loaded_when_switch_is_set(self, *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
        env_file = tmp_path / ".env"
        env_file.write_text(f"{self.CANARY_NAME}={self.CANARY_VALUE}\n", encoding="utf-8")

        load_dotenv(dotenv_path=env_file)

        assert os.environ.get(self.CANARY_NAME) is None
