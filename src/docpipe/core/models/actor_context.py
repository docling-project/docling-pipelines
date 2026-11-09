# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Framework-free caller identity and the pure ownership rule used by services.

``core/`` must not import ``docpipe.api.*``, so roles are plain strings here. The
constants below mirror ``docpipe.api.auth.roles.Role`` and a unit test asserts they
stay equal.
"""

from dataclasses import dataclass

ROLE_VIEWER = "viewer"
ROLE_EDITOR = "editor"
ROLE_ADMIN = "admin"


@dataclass(frozen=True)
class ActorContext:
    """Identity of the caller performing a write.

    Attributes:
        username: Authenticated username, compared with ``created_by`` / ``user_id``.
        roles: Role names held by the caller (``viewer``, ``editor``, ``admin``).
    """

    username: str
    roles: frozenset[str] = frozenset()


def can_modify(*, actor: ActorContext | None, owner: str | None) -> bool:
    """Decide whether ``actor`` may update or delete an asset owned by ``owner``.

    Rules:
        - ``actor is None`` (CLI, library, internal callers) is always allowed.
        - ``admin`` may modify anything.
        - ``editor`` may modify assets it owns, and assets with no owner.
        - Anyone else (``viewer`` or no role) may not modify anything.

    Args:
        actor: The caller, or ``None`` for non-API callers.
        owner: The asset's owner (``created_by`` / ``user_id``); empty or ``None`` means ownerless.

    Returns:
        True when the modification is allowed.
    """
    if actor is None:
        return True
    if ROLE_ADMIN in actor.roles:
        return True
    if ROLE_EDITOR in actor.roles:
        return not owner or owner == actor.username
    return False
