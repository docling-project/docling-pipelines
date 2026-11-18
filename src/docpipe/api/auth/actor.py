# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""FastAPI dependency that turns the current user into an ``ActorContext``."""

from typing import Annotated

from fastapi import Depends

from docpipe.core.models.actor_context import SYSTEM_ACTOR, ActorContext

from .config import get_auth_settings
from .dependencies import get_current_user
from .models import User


def get_actor(user: Annotated[User | None, Depends(get_current_user)]) -> ActorContext:
    """Build the ``ActorContext`` for the current request.

    Returns ``SYSTEM_ACTOR`` when auth is disabled (even if ``get_current_user`` yields a
    local principal) or when there is no user, which services treat as an internal caller:
    always allowed, and ``created_by`` / ``user_id`` stay empty.

    Args:
        user: The authenticated user, if any.

    Returns:
        ``ActorContext`` with the user's username and role names, or ``SYSTEM_ACTOR``.
    """
    if not get_auth_settings().enabled or user is None:
        return SYSTEM_ACTOR
    return ActorContext(username=user.username, roles=frozenset(role.value for role in user.roles))


get_actor_context = get_actor
