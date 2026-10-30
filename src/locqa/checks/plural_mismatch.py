from __future__ import annotations

import re
from collections.abc import Sequence

from locqa import langs
from locqa.arb import icu
from locqa.arb.align import Pair
from locqa.checks.base import Check, CheckContext
from locqa.checks.registry import register
from locqa.models import Finding, IssueType, Severity

# A message that looks like it contains plural/select even when it does not parse.
_COMPLEX_HINT_RE = re.compile(r",\s*(?:plural|select|selectordinal)\s*,")


def _complex_args(nodes: list[icu.Node]) -> dict[str, icu.Argument]:
    return {a.name: a for a in icu.iter_arguments(nodes) if a.is_complex}


def _branch_is_empty(branch: list[icu.Node]) -> bool:
    return all(isinstance(n, str) and not n.strip() for n in branch)


@register
class PluralMismatchCheck(Check):
    """Broken or incomplete ICU plural/select: syntax errors, a lost plural, a missing
    'other' branch, empty branches, categories that do not exist in the target language."""

    issue_type = IssueType.PLURAL_MISMATCH

    def run(self, pairs: Sequence[Pair], ctx: CheckContext) -> list[Finding]:
        target_profile = langs.profile(ctx.target_lang)
        findings = []
        for p in pairs:
            if p.target is None or not p.target.strip():
                continue  # reported as untranslated
            if not (_COMPLEX_HINT_RE.search(p.source) or _COMPLEX_HINT_RE.search(p.target)):
                continue
            try:
                src_args = _complex_args(icu.parse(p.source))
            except icu.IcuSyntaxError:
                continue  # the source itself is broken; nothing to compare against
            problems: list[tuple[Severity, str]] = []
            try:
                tgt_args = _complex_args(icu.parse(p.target))
            except icu.IcuSyntaxError as e:
                problems.append((Severity.HIGH, f"ICU-синтаксис перевода сломан: {e}"))
                tgt_args = {}
            else:
                problems.extend(self._compare(src_args, tgt_args, target_profile))
            if problems:
                severity = max((s for s, _ in problems), key=lambda s: s.rank)
                findings.append(
                    Finding(
                        key=p.key,
                        issue_type=self.issue_type,
                        severity=severity,
                        source=p.source,
                        target=p.target,
                        evidence="; ".join(text for _, text in problems),
                        confidence=1.0 if severity == Severity.HIGH else 0.9,
                    )
                )
        return findings

    @staticmethod
    def _compare(
        src_args: dict[str, icu.Argument],
        tgt_args: dict[str, icu.Argument],
        target_profile: langs.LanguageProfile | None,
    ) -> list[tuple[Severity, str]]:
        problems: list[tuple[Severity, str]] = []
        for name, src in src_args.items():
            tgt = tgt_args.get(name)
            if tgt is None:
                problems.append((Severity.HIGH, f"в переводе нет {{{name}, {src.type}, ...}}"))
            elif tgt.type != src.type:
                problems.append(
                    (Severity.HIGH, f"{{{name}}}: тип {tgt.type} вместо {src.type} в исходнике")
                )
        for name, tgt in tgt_args.items():
            if "other" not in tgt.options:
                problems.append(
                    (Severity.HIGH, f"{{{name}, {tgt.type}}}: нет обязательной ветки other")
                )
            src = src_args.get(name)
            # An empty branch is deliberate only if the source has the same branch empty.
            src_empty = {
                sel
                for sel, branch in (src.options.items() if src else ())
                if _branch_is_empty(branch)
            }
            empty = [
                sel
                for sel, branch in tgt.options.items()
                if _branch_is_empty(branch) and sel not in src_empty
            ]
            if empty:
                problems.append((Severity.MEDIUM, f"{{{name}}}: пустые ветки {', '.join(empty)}"))
            if src is not None and tgt.type == "select":
                lost = sorted(src.options.keys() - tgt.options.keys() - {"other"})
                if lost:
                    problems.append(
                        (Severity.MEDIUM, f"{{{name}, select}}: нет вариантов {', '.join(lost)}")
                    )
            if target_profile and tgt.type == "plural":
                unknown = sorted(
                    s
                    for s in tgt.options
                    if not s.startswith("=") and s not in target_profile.plural_categories
                )
                if unknown:
                    allowed = ", ".join(sorted(target_profile.plural_categories))
                    problems.append(
                        (
                            Severity.LOW,
                            f"{{{name}}}: категорий {', '.join(unknown)} нет в языке перевода "
                            f"(допустимы {allowed})",
                        )
                    )
        return problems
