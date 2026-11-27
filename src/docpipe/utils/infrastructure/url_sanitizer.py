# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Redact credentials from URLs before they reach a log line or an error message.

Pre-authenticated URLs, for example the Microsoft Graph ``@microsoft.graph.downloadUrl`` (``tempauth``),
AWS presigned URLs (``X-Amz-Signature``) and Azure SAS URLs (``sig``), carry the credential in the query
string. Scheme, host, path and non-sensitive parameters are kept so that logs stay useful.
"""

import re
from typing import Final
from urllib.parse import unquote_plus, urlsplit, urlunsplit

REDACTED: Final[str] = "***REDACTED***"

# Parameter names are compared lower-cased, with "-", "_" and "." removed. A name is sensitive when it
# equals one of the exact names or contains one of the keywords. "auth" is exact on purpose so that
# harmless names such as "author" and "authority" are kept.
_SENSITIVE_NAMES: Final[frozenset[str]] = frozenset(
    {"sig", "key", "code", "pwd", "jwt", "session", "sid", "auth", "authorization", "authcode", "authkey"}
)
_SENSITIVE_KEYWORDS: Final[tuple[str, ...]] = (
    "token",
    "tempauth",
    "secret",
    "password",
    "passwd",
    "credential",
    "signature",
    "apikey",
    "accesskey",
    "privatekey",
    "subscriptionkey",
    "sessionid",
)

# "&" can also appear HTML-escaped ("&amp;") or JSON-escaped ("\u0026", used by Go and some Microsoft services)
_PARAM_SEPARATOR: Final[re.Pattern[str]] = re.compile(r"(&amp;|\\u0026|&)", re.IGNORECASE)
_URL_CHAR: Final[str] = r"(?:[^\s'\"<>)\]}\\]|\\u0026)"
_URL_IN_TEXT_PATTERN: Final[re.Pattern[str]] = re.compile(rf"https?://{_URL_CHAR}+", re.IGNORECASE)
# urllib3 and requests report connection failures as "with url: /path?query" without a scheme or host
_REQUEST_PATH_IN_TEXT_PATTERN: Final[re.Pattern[str]] = re.compile(rf"(with url: )({_URL_CHAR}+)")


def is_sensitive_param_name(*, name: str) -> bool:
    """Return True when a URL parameter name indicates that its value is a credential."""
    normalized = re.sub(r"[-_.]", "", unquote_plus(name).lower())
    return normalized in _SENSITIVE_NAMES or any(keyword in normalized for keyword in _SENSITIVE_KEYWORDS)


def _redact_params(*, params: str, redact_value: str) -> str:
    """Redact the value of every credential parameter in an ``a=b&c=d`` query or fragment string."""
    pieces = _PARAM_SEPARATOR.split(params)
    # re.split with a capture group alternates parameters (even index) and separators (odd index)
    for index in range(0, len(pieces), 2):
        name, separator, _ = pieces[index].partition("=")
        if separator and is_sensitive_param_name(name=name):
            pieces[index] = f"{name}={redact_value}"
    return "".join(pieces)


def sanitize_url(url: str, *, redact_value: str = REDACTED) -> str:
    """
    Redact credentials from a URL so that it can be logged or placed in an error message.

    Embedded ``user:password@`` credentials are dropped, and the value of any query or fragment parameter
    that looks like a credential (``tempauth``, ``token``, ``sig``, ``X-Amz-Signature`` and similar) is replaced.

    Args:
        url: A full URL or a path with a query string
        redact_value: The string to substitute for redacted values (default: "***REDACTED***")

    Returns:
        The URL with credentials redacted, or ``redact_value`` when the URL cannot be parsed
    """
    try:
        parts = urlsplit(url)
        host = parts.netloc.rpartition("@")[2]
        query = _redact_params(params=parts.query, redact_value=redact_value) if parts.query else ""
        fragment = _redact_params(params=parts.fragment, redact_value=redact_value) if "=" in parts.fragment else ""
        return urlunsplit((parts.scheme, host, parts.path, query, fragment or parts.fragment))
    except (ValueError, TypeError, AttributeError):
        # Used inside logging calls, so it must never raise: anything that cannot be parsed is replaced entirely
        return redact_value


def split_text_and_urls(*, text: str) -> list[tuple[str, bool]]:
    """
    Split free text into ``(segment, is_url)`` pieces so that URLs and surrounding text can be handled separately.

    Args:
        text: Text that may contain ``http(s)://`` URLs

    Returns:
        Consecutive segments whose concatenation equals ``text``; ``is_url`` is True for URL segments
    """
    segments: list[tuple[str, bool]] = []
    position = 0
    for match in _URL_IN_TEXT_PATTERN.finditer(text):
        if match.start() > position:
            segments.append((text[position : match.start()], False))
        segments.append((match.group(0), True))
        position = match.end()
    if position < len(text):
        segments.append((text[position:], False))
    return segments


def sanitize_urls_in_text(text: str, *, redact_value: str = REDACTED) -> str:
    """
    Redact credentials from every URL embedded in free text such as an exception message.

    Args:
        text: Text that may contain ``http(s)://`` URLs or ``with url: /path?query`` fragments
        redact_value: The string to substitute for redacted values (default: "***REDACTED***")

    Returns:
        The text with credentials in URLs redacted
    """
    text = _URL_IN_TEXT_PATTERN.sub(lambda match: sanitize_url(match.group(0), redact_value=redact_value), text)
    return _REQUEST_PATH_IN_TEXT_PATTERN.sub(
        lambda match: match.group(1) + sanitize_url(match.group(2), redact_value=redact_value), text
    )
