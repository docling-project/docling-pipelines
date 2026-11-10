# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Role guards for REST routes.

``require_role(Role.EDITOR)`` is attached to a route with ``dependencies=[...]`` and
refuses callers whose effective (highest) role is below the minimum with a 403. When
authentication is disabled the guard allows every request.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from docpipe.core.models.ownership import PERMISSION_DENIED_MESSAGE
from docpipe.exceptions.docpipe_exceptions import PermissionDeniedException
from docpipe.utils.infrastructure.audit import OUTCOME_DENIED, audit_event

from .config import get_auth_settings
from .dependencies import get_current_user
from .models import User
from .roles import Role, highest_role


def require_role(min_role: Role) -> Callable[..., None]:
    """Build a FastAPI dependency that requires at least ``min_role``.

    Args:
        min_role: Lowest role allowed to call the route.

    Returns:
        A dependency callable. It raises ``PermissionDeniedException`` (403) when the
        caller's highest role is below ``min_role``, and a 401 when auth is enabled but
        no user could be resolved.
    """

    def _guard(request: Request, user: Annotated[User | None, Depends(get_current_user)]) -> None:
        if not get_auth_settings().enabled:
            return
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if highest_role(user.roles) >= min_role:
            return
        action = f"{request.method} role:{min_role.value}"
        audit_event(
            username=user.username,
            action=action,
            target=request.url.path,
            outcome=OUTCOME_DENIED,
            status_code=status.HTTP_403_FORBIDDEN,
        )
        raise PermissionDeniedException(PERMISSION_DENIED_MESSAGE, action=action, target=request.url.path)

    return _guard
