# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Reusable prompt management utilities.

This module provides utilities for loading, caching, and formatting
prompt templates from JSON files.
"""

import json
from pathlib import Path
from typing import Any

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class PromptManager:
    """Manages prompt templates with caching and formatting.

    This class provides thread-safe loading and caching of prompt templates
    from JSON files. It supports formatting prompts with variables and
    handles common prompt file structures.

    Expected JSON structure:
        {
            "description": "Base prompt description",
            "examples": [
                {"input": "example input", "output": {...}},
                ...
            ]
        }

    Example:
        >>> from pathlib import Path
        >>> prompt_file = Path("prompts/pii_detection.json")
        >>> manager = PromptManager(prompt_file)
        >>> prompt = manager.load_prompt()
        >>> formatted = manager.format_prompt(threshold=0.5)
    """

    def __init__(self, prompt_file: str | Path):
        """Initialize with path to prompt JSON file.

        Args:
            prompt_file: Path to JSON file containing prompt template

        Raises:
            ValueError: If prompt_file is None or empty
        """
        if not prompt_file:
            raise ValueError("prompt_file cannot be None or empty")

        self.prompt_file = Path(prompt_file)
        self._cached_prompt: str | None = None

    def load_prompt(self) -> str:
        """Load and cache prompt from JSON file.

        The prompt is loaded once and cached for subsequent calls.
        The JSON file should contain:
        - "description": Base prompt text
        - "examples": List of example input/output pairs

        Returns:
            Formatted prompt string with description and examples

        Raises:
            FileNotFoundError: If prompt file doesn't exist
            json.JSONDecodeError: If prompt file contains invalid JSON
            KeyError: If required keys are missing from JSON

        Example:
            >>> manager = PromptManager("prompts/detection.json")
            >>> prompt = manager.load_prompt()
            >>> print(prompt[:50])
            'Detect PII and HAP in the following text...'
        """
        if self._cached_prompt is not None:
            return self._cached_prompt

        try:
            with Path(self.prompt_file).open(encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError as exc:
            logger.error("Prompt file not found: %s", self.prompt_file)
            raise DocpipeException(
                message=f"Prompt file not found: {self.prompt_file}. Ensure the file exists and the path is correct.",
                error_code=ErrorCode.INVALID_CONFIGURATION,
            ) from exc
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON in prompt file: %s", self.prompt_file)
            raise DocpipeException(
                message=f"Invalid JSON in prompt file: {self.prompt_file}",
                error_code=ErrorCode.INVALID_CONFIGURATION,
            ) from exc

        # Validate required fields
        if "description" not in data:
            raise DocpipeException(
                message=f"Prompt file missing required 'description' field: {self.prompt_file}",
                error_code=ErrorCode.INVALID_CONFIGURATION,
            )

        # Build prompt from JSON structure
        description = data.get("description", "")
        examples = data.get("examples", [])

        # Only add examples section if examples exist
        if examples:
            prompt = description + "\n\n"
        else:
            prompt = description
        for ex in examples:
            input_text = ex.get("input", "")
            output_data = ex.get("output", {})
            output_json = json.dumps(output_data, indent=2)
            prompt += f'Input:\n"""{input_text}"""\n\nOutput:\n{output_json}\n\n'

        # Strip trailing newlines if no examples were added
        if not examples:
            prompt = prompt.rstrip()

        self._cached_prompt = prompt
        logger.info("Loaded and cached prompt from %s", self.prompt_file)
        return prompt

    def format_prompt(self, **kwargs: Any) -> str:
        """Load prompt and format with variables.

        This method loads the base prompt (using cache if available)
        and formats it with the provided keyword arguments using
        Python's str.format() method.

        Args:
            **kwargs: Variables to substitute in the prompt template

        Returns:
            Formatted prompt string

        Raises:
            KeyError: If a required format variable is missing
            ValueError: If format string is invalid

        Example:
            >>> manager = PromptManager("prompts/detection.json")
            >>> prompt = manager.format_prompt(
            ...     threshold=0.5,
            ...     text="Sample text to analyze"
            ... )
        """
        base_prompt = self.load_prompt()
        try:
            return base_prompt.format(**kwargs)
        except KeyError as exc:
            logger.error("Missing required format variable: %s", exc)
            raise KeyError(f"Missing required format variable in prompt template: {exc}") from exc
        except ValueError as exc:
            logger.error("Invalid format string in prompt: %s", exc)
            raise ValueError(f"Invalid format string in prompt template: {exc}") from exc

    def clear_cache(self) -> None:
        """Clear the cached prompt.

        This forces the next call to load_prompt() to reload from file.
        Useful for testing or when the prompt file has been updated.

        Example:
            >>> manager = PromptManager("prompts/detection.json")
            >>> manager.load_prompt()  # Loads from file
            >>> manager.load_prompt()  # Returns cached version
            >>> manager.clear_cache()
            >>> manager.load_prompt()  # Reloads from file
        """
        self._cached_prompt = None
        logger.debug("Cleared prompt cache for %s", self.prompt_file)

    @property
    def is_cached(self) -> bool:
        """Check if prompt is currently cached.

        Returns:
            True if prompt is cached, False otherwise
        """
        return self._cached_prompt is not None
