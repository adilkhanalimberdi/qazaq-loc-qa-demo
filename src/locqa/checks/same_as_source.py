from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

from locqa import langs
from locqa.arb import icu
from locqa.arb.align import Pair
from locqa.checks.base import Check, CheckContext
from locqa.checks.registry import register
from locqa.models import Finding, IssueType, Severity

_ARG_RE = re.compile(r"\{[^{}]*\}")


def script_of(ch: str) -> str:
    """Unicode script approximated by the first word of the character name: LATIN, CYRILLIC..."""
    try:
        return unicodedata.name(ch).split(" ", 1)[0]
    except ValueError:
        return "UNKNOWN"


def letters(text: str) -> list[str]:
    """Letters that a translator would translate: no arguments, tags, digits or symbols."""
    text = _ARG_RE.sub(" ", text)
    for tag in icu.extract_tags(text):
        text = text.replace(tag, " ")
    return [ch for ch in text if ch.isalpha()]


def dominant_script(texts: Sequence[str]) -> str | None:
    counts = Counter(script_of(ch) for t in texts for ch in letters(t))
    return counts.most_common(1)[0][0] if counts else None


@register
class SameAsSourceCheck(Check):
    """Target equals source. Strings without letters, allowlisted keys and texts, and
    Latin-only strings in a non-Latin source (brands, names) are not reported."""

    issue_type = IssueType.SAME_AS_SOURCE

    def run(self, pairs: Sequence[Pair], ctx: CheckContext) -> list[Finding]:
        cfg = ctx.config
        source_script = dominant_script([p.source for p in pairs])
        findings = []
        for p in pairs:
            if p.target is None:
                continue
            text = p.source.strip()
            if not text or text != p.target.strip():
                continue
            if p.key in cfg.same_as_source_allow_keys or text in cfg.same_as_source_allow_texts:
                continue
            chars = letters(text)
            if not chars:
                continue  # numbers, symbols, placeholders only
            if source_script != "LATIN" and all(script_of(ch) == "LATIN" for ch in chars):
                continue  # Latin brand or name inside a non-Latin source
            words = len(_ARG_RE.sub(" ", text).split())
            severity, confidence, evidence = self._grade(text, words, len(chars), ctx)
            findings.append(
                Finding(
                    key=p.key,
                    issue_type=self.issue_type,
                    severity=severity,
                    source=p.source,
                    target=p.target,
                    evidence=evidence,
                    confidence=confidence,
                )
            )
        return findings

    @staticmethod
    def _grade(
        text: str, words: int, n_letters: int, ctx: CheckContext
    ) -> tuple[Severity, float, str]:
        """Several words are a sentence left untranslated. A single word is often a loanword
        that is spelled the same in both languages ("Профиль"), unless it carries the
        source language's inflection ("Напугать", "Аксессуары")."""
        cfg = ctx.config
        base = f"перевод дословно совпадает с исходником ({words} сл., {n_letters} букв)"
        if words > 1:
            return Severity.MEDIUM, cfg.same_as_source_multi_word_confidence, base
        profile = langs.profile(ctx.source_lang)
        inflection = profile.inflection if profile else None
        word = _ARG_RE.sub(" ", text).strip()
        if inflection and (m := inflection.search(word)):
            return (
                Severity.MEDIUM,
                cfg.same_as_source_inflected_confidence,
                f"{base}; окончание «-{m.group()}» характерно для языка исходника",
            )
        return (
            Severity.LOW,
            cfg.same_as_source_single_word_confidence,
            f"{base}; одно слово, возможно заимствование, одинаковое в обоих языках",
        )
