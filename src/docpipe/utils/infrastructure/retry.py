# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Exponential-backoff retry decorator with pluggable retry logic."""

import time

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

_DEFAULT_ERROR_MESSAGE = "Retry logic misconfigured or no error message provided"


def _parse_retry_result(retry_result: object) -> tuple[bool, str]:
    """Parse the return value of a retry_logic callable.

    Returns (should_retry, error_message). Logs and disables retries when
    retry_result is not a valid (bool, str) tuple.
    """
    if not (isinstance(retry_result, tuple) and len(retry_result) == 2):
        logger.error("retry_logic must return a tuple (bool, str). Disabling retries.")
        return False, _DEFAULT_ERROR_MESSAGE

    should_retry, err_msg = retry_result
    if not isinstance(err_msg, str):
        logger.error("retry_logic second element must be a string. Using default error message.")
        return should_retry, _DEFAULT_ERROR_MESSAGE

    return should_retry, err_msg


def _raise_on_exhaustion(*, max_retries: int, exception: Exception | None, error_message: str) -> None:
    """Raise the appropriate exception when retries are exhausted."""
    if exception:
        logger.error("Failed after %d attempts: %s", max_retries, exception)
        raise exception
    raise DocpipeException(
        f"Retry logic indicated retry on successful call after {max_retries} attempts: {error_message}"
    )


def retry_with_exponential_backoff(max_retries=5, initial_delay=2, max_delay=60, retry_logic=None):
    """
    Decorator for retrying a function with exponential backoff.

    Args:
        max_retries (int): Maximum number of retry attempts.
        initial_delay (float): Initial delay between retries in seconds.
        max_delay (float): Maximum delay between retries in seconds.
        retry_logic (callable): Function that takes (result, exception) and returns a tuple (should_retry: bool, error_message: str).

    Raises:
        DocpipeException: If retry_logic requests retries on a successful call after max_retries, with the provided or default error_message.
        Exception: The original exception if retries are exhausted due to failures.
    """

    def decorator(func):
        """Decorator."""

        def wrapper(*args, **kwargs):
            """Wrapper."""
            retry_count = 0
            delay = initial_delay

            while True:
                result = None
                exception = None
                try:
                    result = func(*args, **kwargs)
                except Exception as e:
                    exception = e

                should_retry = False
                error_message = _DEFAULT_ERROR_MESSAGE
                if retry_logic:
                    retry_result = retry_logic(result=result, exception=exception)
                    should_retry, error_message = _parse_retry_result(retry_result)

                if not should_retry:
                    if exception:
                        raise exception
                    return result

                retry_count += 1
                if retry_count >= max_retries:
                    _raise_on_exhaustion(
                        max_retries=max_retries,
                        exception=exception,
                        error_message=error_message,
                    )

                logger.info("Operation failed on attempt %d. Retrying in %.2f seconds...", retry_count, delay)
                time.sleep(delay)
                delay = min(delay * 2, max_delay)

        if retry_logic is None:
            logger.warning("No retry logic provided. Function will not retry on failure.")
        return wrapper

    return decorator


def should_retry_on_result(result, exception):
    """
    Default retry logic for postgres advisory lock acquisition.

    Args:
        result: The result from the function call
        exception: Any exception that occurred

    Returns:
        Tuple of (should_retry: bool, error_message: str)
    """
    return not bool(result), "Error in acquiring postgres advisory lock"
