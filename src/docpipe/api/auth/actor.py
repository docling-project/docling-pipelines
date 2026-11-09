# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""FastAPI dependency that turns the current user into an ``ActorContext``."""

from typing import Annotated

from fastapi import Depends

from docpipe.core.models.actor_context import ActorContext

from .config import get_auth_settings
from .dependencies import get_current_user
from .models import User


def get_actor(user: Annotated[User | None, Depends(get_current_user)]) -> ActorContext | None:
    """Build the ``ActorContext`` for the current request.

    Returns ``None`` when auth is disabled (even if ``get_current_user`` yields a local
    principal) or when there is no user, which services treat as "CLI / library /
    internal caller": always allowed, and ``created_by`` / ``user_id`` stay empty.

    Note:
        Only fully correct once the session dependency work (task 2.1) lands: until then
        ``get_current_user`` still rejects requests without credentials, so with auth off
        this dependency is only usable when ``get_current_user`` is overridden. It is not
        wired into any route or service yet.

    Args:
        user: The authenticated user, if any.

    Returns:
        ``ActorContext`` with the user's username and role names, or ``None``.
    """
    if not get_auth_settings().enabled or user is None:
        return None
    return ActorContext(username=user.username, roles=frozenset(role.value for role in user.roles))
