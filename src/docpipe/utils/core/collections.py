"""Collection utility functions for list and dictionary operations."""

from collections.abc import Callable, Iterable
from typing import Any


def batch_list[T](*, input_list: list[T], batch_size: int = 20) -> list[list[T]]:
    """
    Split a list into batches of specified size.

    Args:
        input_list: The list to split into batches
        batch_size: Size of each batch (default: 20)

    Returns:
        List of batches, where each batch is a list

    Raises:
        ValueError: If batch_size is not greater than zero.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    return [input_list[i : i + batch_size] for i in range(0, len(input_list), batch_size)]


def process_in_batches[T, R](
    *,
    processor: Callable[..., list[R] | None],
    input_list: Iterable[T],
    batch_size: int = 100,
    **kwargs: Any,
) -> list[R]:
    """
    Processes a list of items in batches using a custom processor function.

    The processor returns a list of results for each batch, or None when the
    batch produces no results. Additional keyword arguments are forwarded to it.

    Args:
        processor: A function that receives each batch, its one-based batch_number,
            its zero-based start_index_offset, and any additional keyword arguments.
            It returns a list of results or None.
        input_list: The input items to process in batches.
        batch_size: The number of items per batch; must be greater than zero.
        **kwargs: Additional keyword arguments passed to the processor.

    Returns:
        The processor results concatenated in batch order.

    Raises:
        ValueError: If batch_size is not greater than zero.
    """
    result_responses = []
    input_list = list(input_list) if not isinstance(input_list, list) else input_list
    input_batches = batch_list(input_list=input_list, batch_size=batch_size)
    start_index_offset = 0

    for batch_number, input_batch in enumerate(input_batches, start=1):
        batch_result = processor(
            input_batch,
            batch_number=batch_number,
            start_index_offset=start_index_offset,
            **kwargs,
        )
        result_responses.extend(batch_result or [])
        start_index_offset += len(input_batch)

    return result_responses


def get_index(*, items: list, key) -> int:
    """
    Get the index of a key in a list.

    Parameters
    ----------
    items : list
        The list to search.
    key : any
        The element to find.

    Returns
    -------
    int
        Index of the key if found, otherwise -1.
    """
    try:
        return items.index(key)
    except ValueError:
        return -1


def lowercase_keys(*, input_dict: dict[str, Any]):
    """
    Convert all keys in a dictionary to lowercase.

    Args:
        input_dict: Dictionary with string keys

    Returns:
        New dictionary with all keys converted to lowercase
    """
    return {key.lower(): value for key, value in input_dict.items()}


def get_list_from_map(obj: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """
    Extract a list of dictionaries from a dictionary.

    Args:
        obj: Source dictionary
        key: Key to extract from

    Returns:
        List of dictionaries, or empty list if key doesn't exist or value is not a list of dicts
    """
    val = obj.get(key)
    if isinstance(val, list):
        return [x for x in val if isinstance(x, dict)]
    return []


def get_map_from_map(obj: dict[str, Any], key: str) -> dict[str, Any]:
    """
    Extract a dictionary from a dictionary.

    Args:
        obj: Source dictionary
        key: Key to extract from

    Returns:
        Dictionary value, or empty dict if key doesn't exist or value is not a dict
    """
    val = obj.get(key)
    return val if isinstance(val, dict) else {}
