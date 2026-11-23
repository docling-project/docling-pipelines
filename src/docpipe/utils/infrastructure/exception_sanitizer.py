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
from collections import deque
from typing import Final

from pydantic import ValidationError

CATEGORY_VALIDATION: Final[str] = "configuration validation error"
CATEGORY_TLS: Final[str] = "TLS verification failed"
CATEGORY_TIMEOUT: Final[str] = "request timed out"
CATEGORY_CONNECTION: Final[str] = "connection failed"
CATEGORY_HTTP: Final[str] = "HTTP request failed"
CATEGORY_DATABASE: Final[str] = "database error"
CATEGORY_CLIENT: Final[str] = "client error"

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
    """Return ``exc`` and every exception reachable from it, nearest first.

    The walk follows ``__cause__``, ``__context__`` (even when ``__suppress_context__`` is set, because a consumer
    that reads the attribute still reaches it) and the members of a ``BaseExceptionGroup``. There is no depth
    limit, so it covers everything ``traceback.format_exception`` can print. A visited set ends the walk on
    cycles and on links reached by more than one path.
    """
    chain: list[BaseException] = []
    seen: set[int] = set()
    pending: deque[BaseException] = deque([exc])
    while pending:
        link = pending.popleft()
        if id(link) in seen:
            continue
        seen.add(id(link))
        chain.append(link)
        if link.__cause__ is not None:
            pending.append(link.__cause__)
        if link.__context__ is not None:
            pending.append(link.__context__)
        if isinstance(link, BaseExceptionGroup):
            pending.extend(link.exceptions)
    return chain


def is_sensitive_chain(*, exc: BaseException) -> bool:
    """Return True when ``exc`` or any exception reachable from it is a known secret-bearing type.

    This is the single sensitivity decision for ``sanitize_exception`` and for callers that choose whether a
    traceback may be logged or chained. It applies ``_classify`` to every link ``traceback.format_exception``
    can print.
    """
    return any(_classify(exc=link) is not None for link in _exception_chain(exc=exc))


class SanitizedCause(ValueError):
    """Stand-in cause whose text is already sanitized; it carries no reference to the original exception."""


def sanitized_cause(*, exc: BaseException, config_key: str) -> BaseException:
    """Return the exception to chain as the cause of a wrapper raised for ``exc``.

    A chain with no sensitive link keeps ``exc`` itself. A sensitive chain is replaced by a ``SanitizedCause``
    holding ``sanitize_exception`` output, so a traceback printed from the wrapper cannot reveal the original.
    The caller must raise the wrapper after its ``except`` block has exited: raising inside the block makes
    Python set ``__context__`` to the original, which would stay reachable.
    """
    if not is_sensitive_chain(exc=exc):
        return exc
    return SanitizedCause(sanitize_exception(exc=exc, config_key=config_key))


def _format_location(*, loc: tuple[int | str, ...]) -> str:
    """Render a Pydantic location with dots for keys and brackets for list indices."""
    text = ""
    for item in loc:
        if isinstance(item, int):
            text += f"[{item}]"
        else:
            text = f"{text}.{item}" if text else item
    return text


def format_pydantic_errors(*, exc: ValidationError, prefix: str = "") -> list[str]:
    """Render each Pydantic error as a message that names its field and never includes input values.

    A missing field becomes ``<path> is not provided``. Any other error with a path becomes ``<path>: <message>``,
    and a model-level error without a path keeps only its message. ``prefix`` is joined to the field path with a
    dot, so a model-level error with a prefix becomes ``<prefix>: <message>``. A leading ``Value error, `` on a
    ``value_error`` becomes ``Value error: ``. Input, context and URLs are never extracted, and ``ctx["error"]``
    is not read. The message is copied verbatim, so a validator that interpolates rejected input into its own
    message still leaks that input; provider validators must not do so.

    Args:
        exc: The Pydantic validation error to render.
        prefix: Optional leading path, such as a config key, prepended to every message.

    Returns:
        One message per error, in the order Pydantic reports them.
    """
    messages: list[str] = []
    for error in exc.errors(include_input=False, include_context=False, include_url=False):
        loc = _format_location(loc=error["loc"])
        path = ".".join(part for part in (prefix, loc) if part)
        message = error["msg"]
        if error["type"] == "value_error" and message.startswith("Value error, "):
            message = "Value error: " + message.removeprefix("Value error, ")
        if error["type"] == "missing":
            messages.append(f"{path} is not provided")
        elif path:
            messages.append(f"{path}: {message}")
        else:
            messages.append(message)
    return messages


def _validation_detail(*, exc: ValidationError, config_key: str) -> str:
    """Render a Pydantic error as category, key paths and constraints, without input values or URLs."""
    parts = format_pydantic_errors(exc=exc, prefix=config_key)
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
        # Every link below the wrapper is a redaction source, classified or not: an unclassified link between
        # the wrapper and the classified one can carry the same secret text.
        redacted = _redact_wrapper_message(exc=exc, causes=chain[1:], replacement=replacement)
        return f"{config_key}: {redacted}" if redacted else fallback
    message = str(exc)
    return message if message else type(exc).__name__
