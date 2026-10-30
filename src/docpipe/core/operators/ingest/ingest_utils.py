# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

import pathlib
from collections.abc import Mapping
from typing import Any

from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


def get_filter_extensions(
    include_filter: str | list[str] | None,
) -> list[str] | None:
    """Get filter extensions."""
    extensions: list[str] | None = None

    if isinstance(include_filter, list):
        return [f".{s.strip()}" if not s.strip().startswith(".") else s.strip() for s in include_filter]

    if include_filter is not None:
        extensions = [
            f".{x.strip()}" if not x.strip().startswith(".") else x.strip() for x in include_filter.split(",")
        ]
    return extensions


def filter_based_on_extension(
    file_path: str,
    excluded_extensions: list[str] | None,
    included_extensions: list[str] | None,
) -> bool:
    """Filter based on extension."""
    extn: str = pathlib.Path(file_path).suffix.lower()
    if excluded_extensions and extn in excluded_extensions:
        logger.info("Skipping %s as the file is in the exclusion list", file_path)
        return True

    if included_extensions and extn not in included_extensions:
        logger.info(
            "Skipping %s as the file type is not supported. Extension: '%s', Included: %s",
            file_path,
            extn,
            included_extensions,
        )
        return True

    return False


def is_doc_previously_processed(
    *, previously_processed_docs_dict: Mapping[str, Any], doc_id: str, modified_time: Any
) -> bool:
    """Returns True if the doc was processed in the previous job run and the doc is not modified since the last processed time."""
    if not previously_processed_docs_dict:
        return False
    doc_entry: Any | None = previously_processed_docs_dict.get(doc_id)
    if not doc_entry:
        return False
    previous_modified_time: Any | None = doc_entry.get("modified_time")
    if previous_modified_time and previous_modified_time >= modified_time:
        return True
    return False


def resolve_msgraph_file_id_to_item_id(
    *,
    file_id: str,
    drive_id: str,
    rest_client,
    token: str,
    original_url: str | None = None,
    strip_path_prefixes: list[str] | None = None,
) -> tuple[str | None, str | None]:
    """
    Resolve a file path or GUID to an actual item ID and drive ID using Microsoft Graph API.

    This is a shared utility function for OneDrive and SharePoint adapters.

    Handles three cases:
    1. If file_id is a path (starts with /), use the path-based API
    2. If file_id is a GUID and original_url is provided, use the /shares endpoint
    3. If file_id is a GUID without URL, try direct access and search methods

    Args:
        file_id: File identifier (path or GUID)
        drive_id: Drive ID (may be overridden if /shares endpoint is used)
        rest_client: RestClient instance for API calls
        token: Microsoft Graph API access token
        original_url: Original SharePoint/OneDrive URL (optional, used for GUID resolution)
        strip_path_prefixes: List of path prefixes to strip if initial resolution fails (e.g., ["Shared Documents/"])

    Returns:
        Tuple of (item_id, actual_drive_id) or (None, None) if resolution fails
    """
    import base64

    from docpipe.integrations.rest_client import RestMethod

    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Case 1: file_id is a path (starts with /)
        if file_id.startswith("/"):
            # Try /shares endpoint first if original_url is provided (most reliable)
            if original_url:
                try:
                    # Encode the URL for the /shares endpoint
                    encoded_url = base64.urlsafe_b64encode(original_url.encode()).decode().rstrip("=")
                    shares_token = f"u!{encoded_url}"

                    shares_endpoint = f"/shares/{shares_token}/driveItem"
                    logger.debug("Trying /shares endpoint for path-based URL")
                    data = rest_client.call_rest_json(
                        method=RestMethod.GET,
                        url=shares_endpoint,
                        headers=headers,
                    )
                    item_id = data.get("id")
                    actual_drive_id = data.get("parentReference", {}).get("driveId")

                    if item_id:
                        if actual_drive_id:
                            logger.info(
                                "Resolved path '%s' via /shares endpoint: item_id=%s, drive_id=%s",
                                file_id,
                                item_id,
                                actual_drive_id,
                            )
                        else:
                            logger.info(
                                "Resolved path '%s' to item ID via /shares endpoint: %s (using provided drive_id)",
                                file_id,
                                item_id,
                            )
                            actual_drive_id = drive_id
                        return item_id, actual_drive_id
                except Exception as shares_error:
                    logger.debug("/shares endpoint failed for path, trying direct path resolution: %s", shares_error)

            # Fallback: Use path-based API: /drives/{drive-id}/root:/{path}
            # Remove leading slash for API call
            path = file_id.lstrip("/")
            endpoint = f"/drives/{drive_id}/root:/{path}"

            logger.debug("Resolving path to item ID using direct path API: %s", path)
            try:
                data = rest_client.call_rest_json(
                    method=RestMethod.GET,
                    url=endpoint,
                    headers=headers,
                )
                item_id = data.get("id")
                logger.info("Resolved path '%s' to item ID: %s", path, item_id)
                return item_id, drive_id
            except Exception as e:
                # If path includes common prefixes, try stripping them
                if strip_path_prefixes:
                    logger.debug("Initial path resolution failed: %s", e)
                    for prefix in strip_path_prefixes:
                        if path.startswith(prefix):
                            stripped_path = path[len(prefix) :]
                            logger.debug("Trying stripped path: %s", stripped_path)
                            try:
                                endpoint = f"/drives/{drive_id}/root:/{stripped_path}"
                                data = rest_client.call_rest_json(
                                    method=RestMethod.GET,
                                    url=endpoint,
                                    headers=headers,
                                )
                                item_id = data.get("id")
                                logger.info("Resolved stripped path '%s' to item ID: %s", stripped_path, item_id)
                                return item_id, drive_id
                            except Exception as strip_error:
                                logger.debug("Stripped path '%s' also failed: %s", stripped_path, strip_error)
                                continue
                # If all attempts failed, raise the original error
                raise e

        # Case 2: file_id is a GUID - try multiple resolution methods
        else:
            # Method 1: If original URL is provided, use /shares endpoint (most reliable for SharePoint URLs)
            if original_url:
                try:
                    # Encode the URL for the /shares endpoint
                    # Format: u!<base64url-encoded-url>
                    encoded_url = base64.urlsafe_b64encode(original_url.encode()).decode().rstrip("=")
                    shares_token = f"u!{encoded_url}"

                    shares_endpoint = f"/shares/{shares_token}/driveItem"
                    logger.debug("Trying /shares endpoint with encoded URL")
                    data = rest_client.call_rest_json(
                        method=RestMethod.GET,
                        url=shares_endpoint,
                        headers=headers,
                    )
                    item_id = data.get("id")
                    # Extract the actual drive ID from the parent reference
                    actual_drive_id = data.get("parentReference", {}).get("driveId")

                    if item_id:
                        if actual_drive_id:
                            logger.info(
                                "Resolved GUID '%s' via /shares endpoint: item_id=%s, drive_id=%s",
                                file_id,
                                item_id,
                                actual_drive_id,
                            )
                        else:
                            logger.info(
                                "Resolved GUID '%s' to item ID via /shares endpoint: %s (using provided drive_id)",
                                file_id,
                                item_id,
                            )
                            actual_drive_id = drive_id
                        return item_id, actual_drive_id
                except Exception as shares_error:
                    logger.debug("/shares endpoint failed: %s", shares_error)

            # Method 2: Try direct access (GUID might be the item ID)
            try:
                endpoint = f"/drives/{drive_id}/items/{file_id}"
                logger.debug("Trying direct access with GUID: %s", file_id)
                data = rest_client.call_rest_json(
                    method=RestMethod.GET,
                    url=endpoint,
                    headers=headers,
                )
                item_id = data.get("id")
                logger.info("Resolved GUID '%s' to item ID via direct access: %s", file_id, item_id)
                return item_id, drive_id
            except Exception as direct_error:
                logger.debug("Direct access failed: %s", direct_error)

            # Method 3: Search for the file using the GUID in the drive
            try:
                # Use search API to find file by unique ID
                search_endpoint = f"/drives/{drive_id}/root/search"
                logger.debug("Searching for file with GUID: %s", file_id)
                search_data = rest_client.call_rest_json(
                    method=RestMethod.GET,
                    url=search_endpoint,
                    headers=headers,
                    query_params={"q": file_id},
                )

                items = search_data.get("value", [])
                if items:
                    # Return the first matching item's ID
                    item_id = items[0].get("id")
                    logger.info("Found file via search, GUID '%s' -> item ID: %s", file_id, item_id)
                    return item_id, drive_id
                logger.warning("No files found in search for GUID: %s", file_id)

            except Exception as search_error:
                logger.debug("Search failed: %s", search_error)

            # All methods failed
            logger.error("Could not resolve file_id '%s' to item ID using any method", file_id)
            return None, None

    except Exception as e:
        logger.exception("Error resolving file_id '%s' to item ID: %s", file_id, e)
        return None, None


def extract_msgraph_file_id_from_url(url: str) -> str | None:
    """
    Extract file ID from OneDrive/SharePoint URL.

    This is a shared utility function for OneDrive and SharePoint adapters.

    Supported URL formats:
    1. Direct file URLs: https://domain.sharepoint.com/?id=/path/to/file.ext
       - File ID is in the 'id' query parameter (URL-encoded path)

    2. Office Online URLs: https://domain.sharepoint.com/:x:/r/path/_layouts/15/Doc.aspx?sourcedoc={GUID}
       - File ID is in the 'sourcedoc' query parameter (GUID format)

    Args:
        url: SharePoint or OneDrive URL

    Returns:
        File ID (either path or GUID) or None if extraction fails
    """
    from urllib.parse import parse_qs, unquote, urlparse

    if not url:
        return None

    try:
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)

        # Method 1: Extract from 'id' parameter (direct file URLs)
        if "id" in query_params:
            file_path = query_params["id"][0]
            # URL decode the path
            file_path = unquote(file_path)
            logger.debug("Extracted file path from 'id' parameter: %s", file_path)
            return file_path

        # Method 2: Extract from 'sourcedoc' parameter (Office Online URLs)
        if "sourcedoc" in query_params:
            sourcedoc = query_params["sourcedoc"][0]
            # Remove curly braces if present (GUID format: {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX})
            guid = sourcedoc.strip("{}")
            logger.debug("Extracted GUID from 'sourcedoc' parameter: %s", guid)
            return guid

        logger.warning("Could not extract file ID from URL: %s", url)
        return None

    except Exception as e:
        logger.exception("Error extracting file ID from URL %s: %s", url, e)
        return None


def handle_msgraph_resolution_result(
    *,
    file_id: str,
    item_id: str | None,
    actual_drive_id: str | None,
    fallback_drive_id: str,
    allow_guid_fallback: bool = False,
    original_url: str | None = None,
) -> tuple[str, str]:
    """
    Handle the result of resolve_msgraph_file_id_to_item_id and return a usable (item_id, drive_id).

    This is a shared utility for OneDrive and SharePoint adapters that encapsulates
    the post-resolution logic: logging on success, raising on unresolvable paths, and optionally
    falling back to using the raw GUID as an item ID (SharePoint behaviour).

    Args:
        file_id: The original file identifier (path or GUID) that was resolved.
        item_id: Resolved item ID, or None if resolution failed.
        actual_drive_id: Resolved drive ID, or None if resolution failed.
        fallback_drive_id: Drive ID to use when actual_drive_id is None.
        allow_guid_fallback: If True and resolution failed for a GUID (not a path),
            use the raw GUID directly as the item ID. Defaults to False.
        original_url: Original URL, used only for error message context.

    Returns:
        Tuple of (item_id, drive_id) guaranteed to be non-None strings.

    Raises:
        ValueError: If resolution failed and either allow_guid_fallback is False, or
            file_id is a path (paths cannot be used as item IDs directly).
    """
    if item_id:
        resolved_drive_id = actual_drive_id or fallback_drive_id
        logger.info("Resolved file ID '%s' to item ID: %s, drive ID: %s", file_id, item_id, resolved_drive_id)
        return item_id, resolved_drive_id

    if file_id.startswith("/"):
        raise ValueError(
            f"Could not resolve file path '{file_id}' to item ID. The path may not exist in the document library."
        )

    if not allow_guid_fallback:
        url_context = f" from URL '{original_url}'" if original_url else ""
        raise ValueError(
            f"Could not resolve file ID '{file_id}'{url_context}. "
            "The URL may be invalid or the file may not be accessible with the provided credentials."
        )

    logger.warning("Could not resolve GUID '%s', using it directly as item ID", file_id)
    return file_id, fallback_drive_id
