# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Factories for creating asset-related instances.

This module provides factory classes for creating repositories and other
asset-related components based on configuration.
"""

from docpipe.core.assets.common.factories.asset_repository_factory import (
    AbstractRepositoryType,
    AssetRepositoryFactory,
    RepositoryType,
)
from docpipe.core.assets.common.factories.attachment_repository_factory import AttachmentRepositoryFactory

__all__ = [
    "AbstractRepositoryType",
    "AssetRepositoryFactory",
    "AttachmentRepositoryFactory",
    "RepositoryType",
]
