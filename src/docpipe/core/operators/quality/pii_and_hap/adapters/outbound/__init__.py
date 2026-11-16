# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Outbound adapters for PII and HAP detection.

Importing this package triggers auto-registration of all adapters with
PIIAndHAPDetectionFactory via the @register_pii_and_hap_detection_adapter decorator.
"""

from .huggingface.adapter import HuggingFaceHAPAdapter
from .litellm.adapter import LiteLLMPIIAndHAPAdapter
from .presidio.adapter import PresidioPIIAdapter
from .watsonx.adapter import WatsonxPIIAndHAPAdapter

__all__ = [
    "HuggingFaceHAPAdapter",
    "LiteLLMPIIAndHAPAdapter",
    "PresidioPIIAdapter",
    "WatsonxPIIAndHAPAdapter",
]
