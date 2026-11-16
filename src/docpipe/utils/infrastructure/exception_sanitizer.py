# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Render exceptions as text that cannot carry a secret value.

Third-party exceptions routinely embed their inputs: Pydantic echoes the offending value, HTTP and
client libraries include URLs, hosts, and credentials, and database drivers include connection
strings. ``sanitize_exception`` reduces those to a fixed category plus the config key path before
the text reaches a log, a node or job message, or run metadata.
"""

from __future__ import annotations

import ssl
from typing import Final

from pydantic import ValidationError

CATEGORY_VALIDATION: Final[str] = "configuration validation error"
CATEGORY_TLS: Final[str] = "TLS verification failed"
CATEGORY_TIMEOUT: Final[str] = "request timed out"
CATEGORY_CONNECTION: Final[str] = "connection failed"
CATEGORY_HTTP: Final[str] = "HTTP request failed"
CATEGORY_DATABASE: Final[str] = "database error"
CATEGORY_CLIENT: Final[str] = "client error"

_MAX_CHAIN_DEPTH: Final[int] = 10

_HTTP_MODULES: Final[frozenset[str]] = frozenset({"requests", "urllib3", "httpx", "aiohttp", "http", "httpcore"})
_DATABASE_MODULES: Final[frozenset[str]] = frozenset(
    {"sqlalchemy", "psycopg", "psycopg2", "asyncpg", "duckdb", "pymilvus", "opensearchpy", "opensearch", "sqlite3"}
)
_CLIENT_MODULES: Final[frozenset[str]] = frozenset(
    {
        "botocore",
        "boto3",
        "msal",
        "msgraph",
        "googleapiclient",
        "google",
        "boxsdk",
        "box_sdk_gen",
        "dropbox",
        "openai",
        "litellm",
        "ollama",
        "huggingface_hub",
        "ibm_watsonx_ai",
        "hvac",
    }
)


def _name_category(*, exc_type: type[BaseException]) -> str | None:
    """Return a network category implied by the class name or hierarchy, if any."""
    if issubclass(exc_type, ssl.SSLError):
        return CATEGORY_TLS
    if issubclass(exc_type, TimeoutError):
        return CATEGORY_TIMEOUT
    if issubclass(exc_type, ConnectionError):
        return CATEGORY_CONNECTION
    name = exc_type.__name__.lower()
    if "ssl" in name or "certificate" in name:
        return CATEGORY_TLS
    if "timeout" in name:
        return CATEGORY_TIMEOUT
    if "connect" in name or "proxy" in name or "nameresolution" in name or "gaierror" in name:
        return CATEGORY_CONNECTION
    return None


def _classify(*, exc: BaseException) -> str | None:
    """Return the fixed category for a single exception, or None when it is not a known risk."""
    if isinstance(exc, ValidationError):
        return CATEGORY_VALIDATION
    exc_type = type(exc)
    module_root = exc_type.__module__.split(".", 1)[0]
    network_category = _name_category(exc_type=exc_type)
    if network_category is not None:
        return network_category
    if module_root in _HTTP_MODULES:
        return CATEGORY_HTTP
    if module_root in _DATABASE_MODULES:
        return CATEGORY_DATABASE
    if module_root in _CLIENT_MODULES:
        return CATEGORY_CLIENT
    return None


def _exception_chain(*, exc: BaseException) -> list[BaseException]:
    """Return ``exc`` followed by its causes and contexts, guarding against cycles."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    pending: BaseException | None = exc
    while pending is not None and id(pending) not in seen and len(chain) < _MAX_CHAIN_DEPTH:
        chain.append(pending)
        seen.add(id(pending))
        pending = pending.__cause__ or pending.__context__
    return chain


def _validation_detail(*, exc: ValidationError, config_key: str) -> str:
    """Render a Pydantic error as category, key paths and constraints, without input values or URLs."""
    parts: list[str] = []
    for error in exc.errors(include_input=False, include_url=False, include_context=False):
        loc = ".".join(str(item) for item in error["loc"])
        key_path = f"{config_key}.{loc}" if loc else config_key
        parts.append(f"{key_path}: {error['msg']}")
    return f"{CATEGORY_VALIDATION} ({'; '.join(parts)})"


def _render_validation_error(*, exc: ValidationError, config_key: str) -> str:
    """Render a Pydantic error prefixed with the config key."""
    return f"{config_key}: {_validation_detail(exc=exc, config_key=config_key)}"


_PLACEHOLDER: Final[str] = "\x00"
_FRAGMENT_LENGTH: Final[int] = 12
_MAX_FRAGMENT_SOURCE: Final[int] = 4096


def _safe_text(*, link: BaseException, config_key: str) -> str:
    """Return the fixed text that stands in for ``link`` once it is known to be a risk."""
    if isinstance(link, ValidationError):
        return _validation_detail(exc=link, config_key=config_key)
    return _classify(exc=link) or ""


def _has_leftover_fragment(*, text: str, sources: list[str]) -> bool:
    """Return True when ``text`` still holds a run of a source string, for example a truncated copy."""
    for source in sources:
        head = source[:_MAX_FRAGMENT_SOURCE]
        for start in range(max(len(head) - _FRAGMENT_LENGTH + 1, 0)):
            if head[start : start + _FRAGMENT_LENGTH] in text:
                return True
    return False


def _redact_wrapper_message(*, exc: BaseException, causes: list[BaseException], replacement: str) -> str | None:
    """Return the wrapper's own message with the text of ``causes`` replaced, or None when that is not safe.

    The wrapper message is kept only when every cause text that it embeds verbatim can be replaced and
    no run of 12 or more characters from a cause text is left behind (a truncated or re-quoted copy).
    """
    message = str(exc)
    sources = sorted({str(cause) for cause in causes if str(cause)}, key=len, reverse=True)
    if not message or not sources:
        return None
    redacted = message
    for source in sources:
        redacted = redacted.replace(source, _PLACEHOLDER)
    if _has_leftover_fragment(text=redacted, sources=sources):
        return None
    return redacted.replace(_PLACEHOLDER, replacement)


def sanitize_exception(*, exc: BaseException, config_key: str) -> str:
    """Return text describing ``exc`` that is safe to log, store, or return.

    Pydantic ``ValidationError`` is rendered with field paths and constraints only. When ``exc`` itself is a
    client, HTTP, database, or network exception it is reduced to a fixed category plus ``config_key``.
    When such an exception is deeper in the cause chain, the wrapper's own message is kept (for example a
    ``DocpipeException`` that tells the user what to fix) with the text of the wrapped exception replaced by
    its category. If the wrapper's text cannot be separated from the cause text, for example because the
    cause is quoted in part, the result is the fixed category alone. Any other exception keeps its own
    message, which the run-level scrubber covers.

    Args:
        exc: The exception to describe.
        config_key: The config key path or node name the failure belongs to.

    Returns:
        A string with no input values from validation errors and no third-party error text.
    """
    chain = _exception_chain(exc=exc)
    for index, link in enumerate(chain):
        category = _classify(exc=link)
        if category is None:
            continue
        fallback = (
            _render_validation_error(exc=link, config_key=config_key)
            if isinstance(link, ValidationError)
            else f"{config_key}: {category}"
        )
        if index == 0:
            return fallback
        replacement = _safe_text(link=link, config_key=config_key)
        redacted = _redact_wrapper_message(exc=exc, causes=chain[index:], replacement=replacement)
        return f"{config_key}: {redacted}" if redacted else fallback
    message = str(exc)
    return message if message else type(exc).__name__
