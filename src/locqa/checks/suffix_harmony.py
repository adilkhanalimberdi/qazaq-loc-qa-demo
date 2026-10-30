from __future__ import annotations

import re
from collections.abc import Sequence

from locqa import langs
from locqa.arb.align import Pair
from locqa.checks.base import Check, CheckContext
from locqa.checks.registry import register
from locqa.models import Finding, IssueType, Severity

# A simple argument, an optional hyphen or apostrophe, then the letters glued to it.
_ARG_SUFFIX_RE = re.compile(r"\{\s*(\w+)\s*\}([-‐–'’]?)(\w+)")


def _variants(suffix: str, profile: langs.LanguageProfile) -> str | None:
    """'-ға/-ге/-қа/-ке/...' for the group of the longest form that ends the suffix."""
    lower = suffix.lower()
    matches = [
        (len(form), group)
        for group in profile.suffix_variants
        for form in group
        if len(form) > 1 and lower.endswith(form)
    ]
    if not matches:
        return None
    _, group = max(matches, key=lambda m: m[0])
    return "/".join(f"-{f}" for f in group)


@register
class SuffixHarmonyCheck(Check):
    """A fixed inflectional suffix right after a placeholder: its correct form depends on the
    last sound of the value inserted at runtime ("{name}-ға" vs "-ге")."""

    issue_type = IssueType.SUFFIX_HARMONY

    def run(self, pairs: Sequence[Pair], ctx: CheckContext) -> list[Finding]:
        profile = langs.profile(ctx.target_lang)
        if profile is None or profile.harmonic_suffix is None:
            return []
        findings = []
        for p in pairs:
            if not p.target:
                continue
            hits = [
                (m.group(1), m.group(2) + m.group(3), m.group(3))
                for m in _ARG_SUFFIX_RE.finditer(p.target)
                if profile.harmonic_suffix.fullmatch(m.group(3))
            ]
            if not hits:
                continue
            parts = []
            for name, written, suffix in hits:
                text = f"{{{name}}}{written}"
                variants = _variants(suffix, profile)
                if variants:
                    text += f" (форма зависит от значения: {variants})"
                parts.append(text)
            findings.append(
                Finding(
                    key=p.key,
                    issue_type=self.issue_type,
                    severity=Severity.MEDIUM,
                    source=p.source,
                    target=p.target,
                    evidence=(
                        "аффикс после плейсхолдера выбран жёстко: "
                        + "; ".join(parts)
                        + ". Переформулировать без аффикса или обработать в коде игры"
                    ),
                    confidence=0.9,
                )
            )
        return findings
