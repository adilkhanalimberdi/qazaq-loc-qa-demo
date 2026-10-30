from __future__ import annotations

from collections.abc import Sequence

from locqa.arb.align import Pair
from locqa.checks.base import Check, CheckContext
from locqa.checks.registry import register
from locqa.glossary import GlossaryTerm
from locqa.models import Finding, IssueType, Severity


def _quote(variants: Sequence[str]) -> str:
    return " / ".join(f"«{v}»" for v in variants)


@register
class GlossaryViolationCheck(Check):
    """A glossary term occurs in the source, but the translation uses a forbidden variant
    or none of the allowed ones. Needs --glossary; terms without a kk value are skipped."""

    issue_type = IssueType.GLOSSARY_VIOLATION

    def run(self, pairs: Sequence[Pair], ctx: CheckContext) -> list[Finding]:
        if ctx.glossary is None:
            return []
        terms = [t for t in ctx.glossary.terms if t.kk_variants or t.forbidden_kk]
        findings = []
        for p in pairs:
            if not p.target or p.target.strip() == p.source.strip():
                continue  # untranslated or same_as_source
            problems = [x for t in terms if (x := self._problem(p, t, ctx))]
            if not problems:
                continue
            findings.append(
                Finding(
                    key=p.key,
                    issue_type=self.issue_type,
                    severity=max((s for s, _, _ in problems), key=lambda s: s.rank),
                    source=p.source,
                    target=p.target,
                    evidence="; ".join(text for _, _, text in problems),
                    confidence=max(c for _, c, _ in problems),
                )
            )
        return findings

    @staticmethod
    def _problem(
        p: Pair, term: GlossaryTerm, ctx: CheckContext
    ) -> tuple[Severity, float, str] | None:
        found = term.find_in_source(p.source)
        if not found:
            return None
        target = p.target or ""
        slang = term.register == "slang"
        forbidden = term.forbidden_regex.search(target) if term.forbidden_regex else None
        if forbidden:
            text = f"«{found}» переведено как «{forbidden.group()}», что запрещено глоссарием"
            if term.kk_variants:
                text += f"; нужно {_quote(term.kk_variants)}"
            return term.severity, 0.95, text
        if term.kk_regex is None or term.kk_regex.search(target):
            return None
        text = f"в исходнике «{found}», в переводе нет {_quote(term.kk_variants)} из глоссария"
        if slang:
            text += " (игровой сленг: допустимы оба варианта, это замечание)"
        # A missing term may be a paraphrase or a pronoun, so confidence is moderate,
        # and lower still in long descriptions, where rewording is common.
        confidence = ctx.config.glossary_missing_confidence * (0.7 if slang else 1.0)
        severity = term.severity
        if len(p.source.split()) > ctx.config.glossary_long_source_words:
            severity, confidence = Severity.LOW, confidence * 0.7
        return severity, round(confidence, 2), text
