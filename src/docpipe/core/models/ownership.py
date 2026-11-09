# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Service-level ownership enforcement shared by flow, project and job run services."""

from docpipe.core.models.actor_context import ActorContext, can_modify
from docpipe.exceptions.docpipe_exceptions import PermissionDeniedException

PERMISSION_DENIED_MESSAGE = "You do not have permission to modify this resource"


def ensure_can_modify(
    *,
    actor: ActorContext | None,
    owner: str | None,
    action: str,
    target: str,
) -> None:
    """Raise ``PermissionDeniedException`` unless ``actor`` may modify an asset owned by ``owner``.

    The exception message is generic and never names the owner.

    Args:
        actor: The caller, or ``None`` for non-API callers (always allowed).
        owner: The asset's owner (``created_by`` / ``user_id``); empty means ownerless.
        action: Short action name, for example ``flow.delete``.
        target: Identifier of the asset being modified.

    Raises:
        PermissionDeniedException: If the actor may not modify the asset.
    """
    if not can_modify(actor=actor, owner=owner):
        raise PermissionDeniedException(PERMISSION_DENIED_MESSAGE, action=action, target=target)
