# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Port for credential authenticators used by ``POST /auth/login``.

Adapters (LDAP, bootstrap administrator) implement ``AuthenticatorPort``. The login
route depends on this port only and never on a concrete adapter.
"""

from abc import ABC, abstractmethod

from .dependencies import LOCAL_PRINCIPAL_USERNAME
from .models import User


class AuthenticatorPort(ABC):
    """Validates a username and password and returns the authenticated user."""

    @abstractmethod
    def authenticate(self, *, username: str, password: str) -> User | None:
        """Validate credentials.

        Implementations must reject the reserved local principal username (see
        ``is_reserved_username``).

        Args:
            username: Username to authenticate.
            password: Password for authentication.

        Returns:
            The authenticated user with its roles, or ``None`` when the credentials are
            invalid.
        """


def is_reserved_username(username: str) -> bool:
    """Return True when ``username`` is the reserved local principal name.

    Args:
        username: Username presented to an authenticator or returned by an identity provider.

    Returns:
        True when the name is reserved and must never authenticate.
    """
    return username == LOCAL_PRINCIPAL_USERNAME
