# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Docling Serve Client for document processing via REST API.

Provides async API support with submit → poll → retrieve pattern for
processing documents through docling-serve service.
"""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from docpipe.core.constants.constants import DoclingClientConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.integrations.base_llm_client import retry_with_backoff
from docpipe.integrations.rest_client import RestClient, RestClientConfig, RestMethod
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class DoclingServeErrorHandler:
    """
    Extensible error handler for docling-serve exceptions.

    Each registered handler is a (matcher, enhancer) pair:
      - matcher(exception) -> bool  : returns True if this handler applies
      - enhancer(exception, context) -> DocpipeException : returns the enhanced exception

    To add a new error type, call register():
        handler.register(my_matcher, my_enhancer)
    """

    def __init__(self, *, base_url: str) -> None:
        self.base_url = base_url
        self._handlers: list[
            tuple[
                Callable[[DocpipeException], bool],
                Callable[[DocpipeException, dict[str, Any]], DocpipeException],
            ]
        ] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register(self._is_format_compatibility_error, self._enhance_format_compatibility_error)

    def register(
        self,
        matcher: Callable[[DocpipeException], bool],
        enhancer: Callable[[DocpipeException, dict[str, Any]], DocpipeException],
    ) -> None:
        """Register a new (matcher, enhancer) pair. Handlers are checked in registration order."""
        self._handlers.append((matcher, enhancer))

    def handle(self, exception: DocpipeException, context: dict[str, Any] | None = None) -> DocpipeException:
        """
        Return an enhanced exception if any registered handler matches, otherwise return the original.

        Args:
            exception: The exception to classify
            context: Optional context passed to the enhancer (e.g. requested_formats)
        """
        ctx = context or {}
        for matcher, enhancer in self._handlers:
            if matcher(exception):
                return enhancer(exception, ctx)
        return exception

    # --- built-in handler: format compatibility ---

    @staticmethod
    def _is_format_compatibility_error(exception: DocpipeException) -> bool:
        if exception.status_code == 422:
            return True
        msg = str(exception).lower()
        return any(
            indicator in msg
            for indicator in (
                "format",
                "to_formats",
                "unsupported",
                "invalid format",
                "unknown format",
                "not supported",
            )
        )

    def _enhance_format_compatibility_error(
        self, exception: DocpipeException, context: dict[str, Any]
    ) -> DocpipeException:
        requested_formats = context.get("requested_formats", [])
        message = (
            f"The docling-serve instance at {self.base_url} rejected the requested output formats. "
            f"This typically occurs when using an older docling-serve version that does not support "
            f"one or more of the requested formats: {requested_formats}. "
            f"\n\nTo resolve this issue:\n"
            f"1. Upgrade docling-serve to the latest version, OR\n"
            f"2. Remove unsupported formats from 'text_extraction.provider_config.additional_formats' in your flow configuration.\n"
            f"\nOriginal error: {exception}"
        )
        return DocpipeException(
            message=message,
            status_code=exception.status_code,
            error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
        )


class DoclingServeClient:
    """
    Client for interacting with docling-serve REST API.

    Supports async document processing with submit → poll → retrieve pattern.
    Handles file submission, status polling with retry logic, and result retrieval.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout: int = 300,
        poll_interval: int = 2,
        max_retries: int = 3,
        verify_ssl: bool = True,
    ):
        """
        Initialize the Docling Serve client.

        Args:
            base_url: Base URL of docling-serve service (required, must not be empty)
            api_key: Optional API key for authentication via X-API-KEY header
            timeout: Request timeout in seconds (default: 300)
            poll_interval: Polling interval in seconds (default: 2)
            max_retries: Maximum retry attempts for API call failures (default: 3)
            verify_ssl: Enable SSL certificate verification (default: True).
                       Set to False only for internal testing with self-signed certificates.

        Raises:
            ValueError: If base_url is empty or whitespace-only
        """
        if not base_url or not base_url.strip():
            raise ValueError("base_url must not be empty")

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.poll_interval = poll_interval

        # Initialize RestClient with max_retries for actual API call failures
        rest_config = RestClientConfig(timeout=self.timeout, max_retries=max_retries, verify_ssl=verify_ssl)
        self.rest_client = RestClient(config=rest_config, base_url=self.base_url)

        # Setup custom headers for API key
        self.custom_headers = {}
        if self.api_key:
            self.custom_headers["X-API-KEY"] = self.api_key

        # Error handler — use register() to add new error types as needed
        self.error_handler = DoclingServeErrorHandler(base_url=self.base_url)

        logger.info("Initialized DoclingServeClient with base_url=%s", self.base_url)

    def _build_options(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Build options dictionary with safe defaults for the docling-serve v1 API.

        Defaults cover parameters that are universally supported across docling-serve
        deployments. Parameters that vary by deployment (ocr_engine, table_mode) are
        NOT included as defaults — they must be explicitly set by the caller.

        Args:
            options: User-provided options to override defaults

        Returns:
            Complete options dictionary with defaults applied
        """
        default_options: dict[str, Any] = {
            "do_ocr": True,
            "pdf_backend": "dlparse_v2",
            "do_table_structure": True,
            "table_cell_matching": True,
            "include_images": True,
            "images_scale": 2.0,
            "image_export_mode": "placeholder",
            # Markdown is mandatory, additional formats come from options
            "to_formats": ["md"],
        }

        if options:
            # Work on a copy so we never mutate the caller's dict (processing_options on the adapter
            # is reused across every document — mutating it would lose additional_formats after the first call)
            opts = dict(options)

            # Pull out additional_formats and append to to_formats before merging the rest
            additional_formats = opts.pop("additional_formats", None)
            if additional_formats:
                to_formats_list: list[str] = default_options["to_formats"]  # type: ignore[assignment]
                for fmt in additional_formats:
                    if fmt and fmt not in to_formats_list:
                        to_formats_list.append(fmt)

            # Pull out any explicit to_formats override before the general update
            user_to_formats = opts.pop("to_formats", None)
            default_options.update(opts)

            if user_to_formats:
                # Ensure "md" is always present
                if "md" not in user_to_formats:
                    user_to_formats.insert(0, "md")
                default_options["to_formats"] = user_to_formats

        # Strip None values — requests serialises None as the string "None" which the server rejects
        return {k: v for k, v in default_options.items() if v is not None}

    def submit_document(
        self,
        *,
        file_path: str | None = None,
        binary_content: bytes | None = None,
        filename: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        """
        Submit a document for processing.

        Args:
            file_path: Path to file to process (mutually exclusive with binary_content)
            binary_content: Binary content of file (mutually exclusive with file_path)
            filename: Filename to use when binary_content is provided. Preserves file extension
                     for proper MIME type detection. If not provided, uses default fallback filename.
            options: Processing options (OCR, tables, images, PDF backend, etc.)

        Returns:
            Task ID for tracking the processing job

        Raises:
            ValueError: If neither or both file_path and binary_content provided
            FileNotFoundError: If file_path does not exist
            DocpipeException: For HTTP or network errors
        """
        if (file_path is None) == (binary_content is None):
            raise ValueError("Provide exactly one of file_path or binary_content")

        # Read file if path provided
        content: bytes
        actual_filename: str
        if file_path:
            path = Path(file_path)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")
            content = path.read_bytes()
            actual_filename = path.name
            logger.info("Submitting document: %s", file_path)
        else:
            # binary_content is guaranteed to be bytes here due to validation above
            content = binary_content  # type: ignore[assignment]
            actual_filename = filename if filename else OperatorConstants.Extraction.DEFAULT_FALLBACK_FILENAME
            logger.info("Submitting document from binary content with filename: %s", actual_filename)

        # Submit request using multipart/form-data
        endpoint = "/v1/convert/file/async"
        return self._submit_request_multipart(
            endpoint=endpoint,
            file_content=content,
            filename=actual_filename,
            options=options,
        )

    def _submit_request_multipart(
        self,
        *,
        endpoint: str,
        file_content: bytes,
        filename: str,
        options: dict[str, Any] | None = None,
    ) -> str:
        """
        Submit HTTP multipart/form-data request and extract task ID.

        Args:
            endpoint: API endpoint path
            file_content: Binary file content
            filename: Name of the file
            options: Processing options dictionary

        Returns:
            Task ID from response

        Raises:
            DocpipeException: For HTTP or network errors, including unsupported format errors
        """
        # Determine MIME type based on file extension
        mime_type = "application/octet-stream"
        if filename:
            ext = Path(filename).suffix.lower()
            mime_map = {
                ".html": "text/html",
                ".htm": "text/html",
                ".md": "text/markdown",
                ".txt": "text/plain",
                ".pdf": "application/pdf",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            }
            mime_type = mime_map.get(ext, "application/octet-stream")

        # Build multipart form data
        files = {"files": (filename, file_content, mime_type)}

        # Build form data with options as individual fields
        data = self._build_options(options)

        try:
            result = self.rest_client.call_rest_multipart(
                method=RestMethod.POST,
                url=endpoint,
                files=files,
                form_data=data,
                headers=self.custom_headers,
            )
        except DocpipeException as e:
            context = {"requested_formats": data.get("to_formats", [])}
            enhanced = self.error_handler.handle(e, context)
            raise enhanced from e

        task_id = result.get("task_id")
        if not task_id:
            raise DocpipeException(
                message="No task_id in response",
                status_code=500,
                error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            )

        logger.info("Document submitted successfully, task_id=%s, params=%s", task_id, list(data.keys()))
        return task_id

    def _poll_for_completion(
        self,
        *,
        task_id: str,
        poll_interval: int | None = None,
        timeout: int = 7200,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """
        Poll task status until a terminal status is reached.

        Args:
            task_id: Task ID to poll
            poll_interval: Override default polling interval in seconds
            timeout: Maximum time to wait in seconds (default: 7200 = 2 hours)
            filename: Optional filename associated with the task for logging

        Returns:
            Final status response dictionary

        Raises:
            DocpipeException: For failure status, HTTP errors, or timeout exceeded
        """
        interval = poll_interval if poll_interval is not None else self.poll_interval
        start_time = time.time()

        logger.info("Polling status for task_id=%s with timeout=%ss", task_id, timeout)

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise DocpipeException(
                    message=f"Polling timeout after {timeout} seconds for task {task_id}",
                    status_code=500,
                    error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                )

            try:
                endpoint = f"/v1/status/poll/{task_id}"
                result = self._check_status(endpoint=endpoint)
                task_status = result.get("task_status", "unknown").upper()
                file_label = filename if filename is not None else "unknown"

                logger.info("Polling task %s for file '%s': status=%s", task_id, file_label, task_status)

                if task_status == "SUCCESS":
                    logger.info("Task %s completed successfully", task_id)
                    return result

                if task_status == "FAILURE":
                    error_msg = result.get("error_message", "Unknown error")
                    logger.error(
                        "Task %s failed with error: %s. "
                        "If this is an 'Internal processing error', check that the processing "
                        "parameters sent to docling-serve are supported by this deployment "
                        "(e.g. ocr_engine, table_mode, pdf_backend). "
                        "See the submission log above for the params that were sent.",
                        task_id,
                        error_msg,
                        extra={"task_id": task_id, "full_response": result},
                    )
                    raise DocpipeException(
                        message=f"Task {task_id} failed: {error_msg}",
                        status_code=500,
                        error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                    )

                # Continue polling for PENDING/STARTED/unknown statuses
                logger.debug("Task %s status: %s, continuing to poll...", task_id, task_status)
                time.sleep(interval)

            except DocpipeException as e:
                # Re-raise DocpipeException (including FAILURE status)
                if e.error_code != ErrorCode.CONNECTION_ERROR:
                    raise
                # For connection errors, log and retry
                logger.warning("Connection error during polling: %s, retrying...", e)
                time.sleep(interval)

    def poll_status(
        self,
        *,
        task_id: str,
        poll_interval: int | None = None,
        timeout: int = 7200,
    ) -> dict[str, Any]:
        """
        Poll task status until completion with timeout.

        Args:
            task_id: Task ID to poll
            poll_interval: Override default polling interval in seconds
            timeout: Maximum time to wait in seconds (default: 7200 = 2 hours)

        Returns:
            Final status response with terminal state information

        Raises:
            DocpipeException: For failure status, HTTP errors, or timeout exceeded
        """
        return self._poll_for_completion(
            task_id=task_id,
            poll_interval=poll_interval,
            timeout=timeout,
        )

    @retry_with_backoff(
        max_retries=DoclingClientConstants.STATUS_404_MAX_RETRIES,
        initial_delay=DoclingClientConstants.STATUS_404_BACKOFF_BASE,
        backoff_factor=2.0,
        exceptions=(DocpipeException,),
    )
    def _check_status(self, *, endpoint: str) -> dict[str, Any]:
        """
        Check task status via HTTP request with retry logic for 404 errors.

        Retries on 404 errors to handle:
        - Pod restarts/terminations during HPA scaling
        - Load balancer routing issues during pod lifecycle events
        - Transient network issues

        Args:
            endpoint: Status endpoint path

        Returns:
            Status response dictionary

        Raises:
            DocpipeException: For HTTP errors (after retries for 404)
        """
        try:
            return self.rest_client.call_rest_json(
                method=RestMethod.GET,
                url=endpoint,
                headers=self.custom_headers,
            )
        except DocpipeException as e:
            # Only retry on 404 errors (task not found during pod transitions)
            if e.status_code == 404:
                logger.warning(
                    "Task not found (404) at %s. This may occur during pod restarts or HPA scaling. Retrying...",
                    endpoint,
                )
                raise  # Let decorator handle retry
            # For other errors, raise immediately without retry
            raise

    def get_result(self, *, task_id: str) -> dict[str, Any]:
        """
        Retrieve processed document result.

        Args:
            task_id: Task ID to retrieve result for

        Returns:
            Processed document data as dictionary

        Raises:
            DocpipeException: For HTTP or network errors
        """
        endpoint = f"/v1/result/{task_id}"
        logger.info("Retrieving result for task_id=%s", task_id)

        result = self.rest_client.call_rest_json(
            method=RestMethod.GET,
            url=endpoint,
            headers=self.custom_headers,
        )

        logger.info("Result retrieved successfully for task_id=%s", task_id)
        return result

    def process_document(
        self,
        *,
        file_path: str | None = None,
        binary_content: bytes | None = None,
        filename: str | None = None,
        options: dict[str, Any] | None = None,
        poll_interval: int | None = None,
        timeout: int = 7200,
    ) -> dict[str, Any]:
        """
        Convenience method combining submit → poll → retrieve.

        Args:
            file_path: Path to file to process
            binary_content: Binary content of file
            filename: Filename to use when binary_content is provided. Preserves file extension
                     for proper MIME type detection. If not provided, defaults to "document.pdf".
            options: Processing options
            poll_interval: Override default polling interval
            timeout: Maximum time to wait in seconds (default: 7200 = 2 hours)

        Returns:
            Processed document data as dictionary

        Raises:
            ValueError: If neither or both file_path and binary_content provided
            FileNotFoundError: If file_path does not exist
            DocpipeException: For HTTP, network, or processing errors
        """
        # Submit document
        task_id = self.submit_document(
            file_path=file_path,
            binary_content=binary_content,
            filename=filename,
            options=options,
        )

        # Poll until completion and only retrieve result after SUCCESS
        final_response = self._poll_for_completion(
            task_id=task_id,
            poll_interval=poll_interval,
            timeout=timeout,
            filename=filename,
        )
        logger.info("Final Status before: %s, %s", task_id, final_response)
        final_status = str(final_response.get("task_status", "")).upper()
        logger.info("Final Status: %s, %s", task_id, final_status)
        if final_status != "SUCCESS":
            error_message = final_response.get("error_message", "Unknown Error")
            raise DocpipeException(
                message=f"Task {task_id} did not complete successfully with error message: {error_message}",
                status_code=500,
                error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            )

        return self.get_result(task_id=task_id)
