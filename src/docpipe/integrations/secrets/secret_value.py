# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Opaque wrapper for resolved secret material.

``SecretValue`` holds a resolved secret and refuses to render it through any
implicit path (``repr``, ``str``, ``format``, pickling, JSON encoding,
iteration, comparison with ``str``). Copying returns the same immutable
instance. The only way to read the underlying string is the explicit
:meth:`SecretValue.reveal` call, which is intended for client construction
sites only.

It is deliberately NOT a ``str`` subclass: a ``str`` subclass would join,
slice, concatenate, and serialize as plain text without any hook.

This module has no ``docpipe`` imports so that low-level utilities can use it
without import cycles.
"""

from typing import Any, NoReturn

MASK: str = "***"


class SecretValue:
    """Opaque holder for a resolved secret string."""

    __slots__ = ("_value",)

    def __init__(self, *, value: str) -> None:
        object.__setattr__(self, "_value", value)

    def reveal(self) -> str:
        """Return the underlying secret. Call only when building a client."""
        return str(object.__getattribute__(self, "_value"))

    def __setattr__(self, name: str, value: Any) -> None:
        msg = "SecretValue is immutable"
        raise AttributeError(msg)

    def __delattr__(self, name: str) -> None:
        msg = "SecretValue is immutable"
        raise AttributeError(msg)

    def __repr__(self) -> str:
        return f"SecretValue({MASK})"

    def __str__(self) -> str:
        return MASK

    def __format__(self, format_spec: str) -> str:
        return MASK

    def __reduce__(self) -> NoReturn:
        msg = "SecretValue cannot be pickled"
        raise TypeError(msg)

    def __reduce_ex__(self, protocol: Any) -> NoReturn:
        msg = "SecretValue cannot be pickled"
        raise TypeError(msg)

    def __copy__(self) -> "SecretValue":
        # Immutable: sharing the same instance leaks nothing and keeps the
        # value usable for libraries that copy their configuration.
        return self

    def __deepcopy__(self, memo: Any) -> "SecretValue":
        return self

    def __iter__(self) -> NoReturn:
        msg = "SecretValue is not iterable"
        raise TypeError(msg)

    def __len__(self) -> NoReturn:
        msg = "SecretValue has no length"
        raise TypeError(msg)

    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)


def secret_json_default(obj: Any) -> str:
    """``json.dumps(default=...)`` hook that masks a ``SecretValue``.

    Without this hook ``json.dumps`` raises ``TypeError`` for a ``SecretValue``,
    so the value can never be serialized by accident.
    """
    if isinstance(obj, SecretValue):
        return MASK
    msg = f"Object of type {type(obj).__name__} is not JSON serializable"
    raise TypeError(msg)
