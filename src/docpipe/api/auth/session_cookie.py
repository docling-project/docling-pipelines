# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Helpers that set and clear the session cookie.

The cookie is ``HttpOnly``, ``SameSite=Lax`` and ``Path=/``. It carries the ``Secure``
attribute when the request is served over HTTPS, when ``DOCPIPE_TRUST_PROXY_HEADERS=true``
and the proxy reports ``X-Forwarded-Proto: https``, or when ``DOCPIPE_AUTH_COOKIE_SECURE=true``.
"""

from typing import Literal

from fastapi import Request, Response

from .config import AuthSettings

COOKIE_PATH = "/"
COOKIE_SAMESITE: Literal["lax"] = "lax"
FORWARDED_PROTO_HEADER = "x-forwarded-proto"


def is_secure_request(*, request: Request, settings: AuthSettings) -> bool:
    """Decide whether the session cookie must carry the ``Secure`` attribute.

    Args:
        request: Current request.
        settings: Current auth settings.

    Returns:
        True when the request is HTTPS, a trusted proxy reports HTTPS, or the override is set.
    """
    if settings.cookie_secure or request.url.scheme == "https":
        return True
    if settings.trust_proxy_headers:
        # With several proxies the header is a comma-separated list; the rightmost entry is
        # the one the trusted proxy appended.
        forwarded_proto = request.headers.get(FORWARDED_PROTO_HEADER, "").split(",")[-1].strip().lower()
        return forwarded_proto == "https"
    return False


def set_session_cookie(
    *,
    response: Response,
    request: Request,
    settings: AuthSettings,
    token: str,
    max_age_seconds: int,
) -> None:
    """Set the session cookie on ``response``.

    Args:
        response: Response to carry the ``Set-Cookie`` header.
        request: Current request, used to decide the ``Secure`` attribute.
        settings: Current auth settings (cookie name and overrides).
        token: Signed JWT to store.
        max_age_seconds: Cookie lifetime, matching the token lifetime.
    """
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=max_age_seconds,
        path=COOKIE_PATH,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=is_secure_request(request=request, settings=settings),
    )


def clear_session_cookie(*, response: Response, request: Request, settings: AuthSettings) -> None:
    """Expire the session cookie on ``response``.

    Args:
        response: Response to carry the expiring ``Set-Cookie`` header.
        request: Current request, used to decide the ``Secure`` attribute.
        settings: Current auth settings (cookie name and overrides).
    """
    response.delete_cookie(
        key=settings.cookie_name,
        path=COOKIE_PATH,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=is_secure_request(request=request, settings=settings),
    )
