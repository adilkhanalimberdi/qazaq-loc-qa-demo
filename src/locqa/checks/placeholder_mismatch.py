from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from locqa.arb import icu
from locqa.arb.align import Pair
from locqa.checks.base import Check, CheckContext
from locqa.checks.registry import register
from locqa.models import Finding, IssueType, Severity


def _diff(source: Counter[str], target: Counter[str]) -> tuple[list[str], list[str]]:
    missing = sorted((source - target).elements())
    extra = sorted((target - source).elements())
    return missing, extra


def _describe(label: str, missing: list[str], extra: list[str]) -> str:
    parts = []
    if missing:
        parts.append(f"нет {' '.join(missing)}")
    if extra:
        parts.append(f"лишние {' '.join(extra)}")
    return f"{label}: {', '.join(parts)}"


@register
class PlaceholderMismatchCheck(Check):
    """ICU arguments, markup tags and line breaks must match the source."""

    issue_type = IssueType.PLACEHOLDER_MISMATCH

    def run(self, pairs: Sequence[Pair], ctx: CheckContext) -> list[Finding]:
        findings = []
        for p in pairs:
            if p.target is None or not p.target.strip():
                continue  # reported as untranslated
            problems: list[tuple[Severity, float, str]] = []

            src_args = icu.extract_arguments(p.source)
            tgt_args = icu.extract_arguments(p.target)
            if icu.has_complex_argument(p.source) or icu.has_complex_argument(p.target):
                # Plural/select branches legitimately repeat or omit arguments; compare names only.
                src_args, tgt_args = Counter(set(src_args)), Counter(set(tgt_args))
            missing, extra = _diff(src_args, tgt_args)
            if missing or extra:
                problems.append(
                    (
                        Severity.HIGH,
                        1.0,
                        _describe(
                            "плейсхолдеры",
                            [f"{{{a}}}" for a in missing],
                            [f"{{{a}}}" for a in extra],
                        ),
                    )
                )

            missing, extra = _diff(icu.extract_tags(p.source), icu.extract_tags(p.target))
            if missing or extra:
                problems.append((Severity.MEDIUM, 0.95, _describe("теги", missing, extra)))

            # Translators often reflow lines, so a line-break difference alone is noise
            # unless enabled in config; it is still mentioned next to real problems.
            src_nl, tgt_nl = icu.count_newlines(p.source), icu.count_newlines(p.target)
            if src_nl != tgt_nl and (problems or ctx.config.report_newline_mismatch):
                problems.append(
                    (
                        Severity.LOW,
                        0.8,
                        f"переносы строк \\n: {src_nl} в исходнике, {tgt_nl} в переводе",
                    )
                )

            if problems:
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
