# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Role model for authorization.

Roles are ordered ``viewer`` < ``editor`` < ``admin``. A higher role includes the
rights of every role below it.
"""

from enum import StrEnum
from typing import Any


class Role(StrEnum):
    """Authorization role carried in the session and the JWT ``roles`` claim."""

    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        """Return the numeric rank of this role (higher means more rights)."""
        return _ROLE_RANK[self.value]

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Role):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, Role):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, Role):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, Role):
            return NotImplemented
        return self.rank >= other.rank


_ROLE_RANK: dict[str, int] = {
    Role.VIEWER.value: 0,
    Role.EDITOR.value: 1,
    Role.ADMIN.value: 2,
}


def parse_roles(raw: Any) -> list[Role]:
    """Parse a JWT ``roles`` claim into a list of known roles.

    Unknown values are ignored. A missing, malformed or empty claim yields
    ``[Role.VIEWER]`` so that callers fail closed.

    Args:
        raw: Raw claim value from the decoded token payload.

    Returns:
        List of recognised roles, never empty.
    """
    roles: list[Role] = []
    if isinstance(raw, list | tuple | set | frozenset):
        for item in raw:
            try:
                role = Role(item)
            except ValueError:
                continue
            if role not in roles:
                roles.append(role)
    return roles or [Role.VIEWER]


def highest_role(roles: list[Role]) -> Role:
    """Return the highest role in ``roles``, or ``Role.VIEWER`` when empty."""
    return max(roles, default=Role.VIEWER)
