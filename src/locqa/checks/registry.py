"""Registry of available checks, selectable with --only / --skip."""

from __future__ import annotations

from collections.abc import Iterable

from locqa.checks.base import Check
from locqa.errors import InputError
from locqa.models import IssueType

_REGISTRY: dict[str, type[Check]] = {}


def register(cls: type[Check]) -> type[Check]:
    name = cls.issue_type.value
    if name in _REGISTRY:
        raise ValueError(f"check '{name}' registered twice")
    _REGISTRY[name] = cls
    return cls


def available() -> list[str]:
    """Registered check names in IssueType declaration order."""
    order = [t.value for t in IssueType]
    return sorted(_REGISTRY, key=order.index)


def get_checks(only: Iterable[str] | None = None, skip: Iterable[str] = ()) -> list[Check]:
    only = set(only) if only else None
    skip = set(skip)
    unknown = sorted(((only or set()) | skip) - _REGISTRY.keys())
    if unknown:
        raise InputError(
            f"неизвестные проверки: {', '.join(unknown)}. Доступны: {', '.join(available())}"
        )
    return [
        _REGISTRY[name]()
        for name in available()
        if (only is None or name in only) and name not in skip
    ]
