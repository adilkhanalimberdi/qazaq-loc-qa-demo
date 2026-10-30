"""Splitting translatable text into words, shared by the checks."""

from __future__ import annotations

import re

# Letters, optionally joined by an apostrophe: "o‘yin", "HUD’ni".
WORD_RE = re.compile(r"[^\W\d_]+(?:[‘’'ʻ`][^\W\d_]+)*")
# Arguments, tags, URLs and printf-style specifiers (%s, %1$d) are not words of any language.
MARKUP_RE = re.compile(r"\{[^{}]*\}|<[^<>]*>|\b\w+://\S+|%(?:\d+\$)?[sdif]")


def mask_markup(text: str) -> str:
    """Markup replaced by spaces of the same length, so match offsets stay valid."""
    return MARKUP_RE.sub(lambda m: " " * len(m.group()), text)


def match_case(word: str, like: str) -> str:
    """`word` written in the case pattern of `like`: UPPER, Capitalised or lower."""
    if like.isupper() and len(like) > 1:
        return word.upper()
    if like[:1].isupper():
        return word[:1].upper() + word[1:]
    return word
