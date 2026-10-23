"""Concurrency utilities for parallel processing and context propagation."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, TypeVar

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

# Define type variables for generic function typing
T = TypeVar("T")  # input batch type
R = TypeVar("R")  # worker_fn return type


def _append_result(batch_result, result_extractor, results):
    """Handle extraction and appending of results."""
    if not batch_result:
        return

    # Apply extractor if provided
    final_result = result_extractor(batch_result) if result_extractor else batch_result

    if not final_result:
        return

    if isinstance(final_result, list):
        results.extend(final_result)
    else:
        results.append(final_result)


def process_batches_in_parallel[T, R](
    *,
    batches: list[T],
    worker_fn: Callable[[T], R],
    max_workers: int = OperatorConstants.Misc.DEFAULT_MAX_THREADS,
    result_extractor: Callable[[R], list[Any] | None] | None = None,
) -> list[Any]:
    """
    Run a worker function in parallel on batches and merge results.

    Args:
        batches (List[T]): The list of batches to process.
        worker_fn (Callable[[T], R]): A function that takes a batch and returns results.
        max_workers (int, optional): Number of threads to use. Defaults to OperatorConstants.DEFAULT_MAX_THREADS.
        result_extractor (Callable[[R], List[Any]], optional):
            Function to extract/flatten results from worker_fn's return.
            If None, results are returned as-is.

    Returns:
        List[Any]: Combined results from all batches.
    """

    results: list[Any] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_batch = {submit_task_with_context_propagation(executor, worker_fn, batch): batch for batch in batches}

        for future in as_completed(future_to_batch):
            try:
                batch_result = future.result()
                _append_result(batch_result, result_extractor, results)

            except Exception as e:
                logger.error("Batch %s failed with %s", future_to_batch[future], e)

    return results


def run_with_session_info[T](session_info: Any, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    A utility function that runs a function with the given session_info in the current thread/context.
    This is particularly useful for ThreadPoolExecutor workers to ensure they have the correct session_info.

    Args:
        session_info: The session_info object to set in the current thread/context
        func: The function to execute
        *args: Positional arguments to pass to the function
        **kwargs: Keyword arguments to pass to the function

    Returns:
        The result of the function execution
    """
    if session_info:
        from docpipe.core.models.session_info import set_session_info

        # Set the session_info in the current thread/context
        set_session_info(session_info)

    # Execute the function with the provided arguments
    return func(*args, **kwargs)


def submit_task_with_context_propagation(executor: "ThreadPoolExecutor", func: "Callable", *args, **kwargs):
    """
    Submit a task to ThreadPoolExecutor with session_info context propagation.

    This function ensures that session information is properly propagated to worker threads.

    Args:
        executor: ThreadPoolExecutor instance to submit the task to
        func: The function to execute in the worker thread
        *args: Positional arguments to pass to the function
        **kwargs: Keyword arguments to pass to the function

    Returns:
        Future object representing the execution of the task

    Example:
        with ThreadPoolExecutor(max_workers=4) as executor:
            future = submit_task_with_context_propagation(executor, my_function, arg1, arg2, key=value)
            result = future.result()
    """
    from docpipe.core.models.session_info import get_session_info

    current_session = get_session_info()

    return executor.submit(run_with_session_info, current_session, func, *args, **kwargs)


__all__ = [
    "process_batches_in_parallel",
    "run_with_session_info",
    "submit_task_with_context_propagation",
]
