# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Docpipe — top-level package exposing the public API."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

__all__ = ["DocpipeFlowManager"]


def __getattr__(name: str) -> Any:
    """Import ``DocpipeFlowManager`` on first access (PEP 562).

    Importing it pulls in the whole flow engine, which costs several seconds. A process that only needs a
    sub-package, such as an isolated custom operator worker, must not pay that on ``import docpipe.<sub-package>``.
    """
    if name == "DocpipeFlowManager":
        from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

        return DocpipeFlowManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
