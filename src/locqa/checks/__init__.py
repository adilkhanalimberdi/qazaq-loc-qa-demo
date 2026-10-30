"""Checks register themselves on import; import every check module here."""

from locqa.checks import (  # noqa: F401
    glossary_violation,
    inconsistent_term,
    length_overflow,
    orthography,
    placeholder_mismatch,
    plural_mismatch,
    same_as_source,
    suffix_harmony,
    untranslated,
    wrong_language,
)
from locqa.checks.base import Check, CheckContext
from locqa.checks.registry import available, get_checks, register

__all__ = ["Check", "CheckContext", "available", "get_checks", "register"]
