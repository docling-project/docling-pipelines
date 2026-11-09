# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Group-to-role mapping shared by the LDAP and OIDC authenticators.

Group identifiers are compared as trimmed exact strings. LDAP distinguished names are
compared case-insensitively. A caller that matches no mapping receives the default role,
and a caller that matches several receives the highest matching role.
"""

from collections.abc import Iterable, Mapping

from .roles import Role


def _normalize(*, value: str, case_insensitive: bool) -> str:
    """Trim ``value`` and, for LDAP distinguished names, fold its case."""
    trimmed = value.strip()
    return trimmed.casefold() if case_insensitive else trimmed


def resolve_role(
    *,
    groups: Iterable[str],
    role_mapping: Mapping[Role, tuple[str, ...]],
    default_role: Role,
    case_insensitive: bool = False,
) -> Role:
    """Map the caller's group identifiers to a single role.

    Args:
        groups: Group identifiers reported by the directory or the identity provider.
        role_mapping: Configured group identifiers per role.
        default_role: Role of a caller that matches no mapped group (``viewer`` by default).
        case_insensitive: Compare identifiers case-insensitively (LDAP distinguished names).

    Returns:
        The highest role with a matching group, or ``default_role`` when none matches.
    """
    caller_groups = {
        _normalize(value=group, case_insensitive=case_insensitive) for group in groups if isinstance(group, str)
    }
    caller_groups.discard("")
    matched: list[Role] = []
    for role, mapped_groups in role_mapping.items():
        mapped = {_normalize(value=group, case_insensitive=case_insensitive) for group in mapped_groups}
        if caller_groups & mapped:
            matched.append(role)
    return max(matched, default=default_role)
