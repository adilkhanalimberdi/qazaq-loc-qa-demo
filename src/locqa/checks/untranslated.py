from __future__ import annotations

from collections.abc import Sequence

from locqa.arb.align import Pair
from locqa.checks.base import Check, CheckContext
from locqa.checks.registry import register
from locqa.models import Finding, IssueType, Severity


@register
class UntranslatedCheck(Check):
    """Key is missing in the target file, or its value is empty or whitespace only."""

    issue_type = IssueType.UNTRANSLATED

    def run(self, pairs: Sequence[Pair], ctx: CheckContext) -> list[Finding]:
        findings = []
        for p in pairs:
            if not p.source.strip():
                continue  # nothing to translate
            if p.target is None:
                evidence = "ключа нет в целевом файле"
            elif not p.target.strip():
                evidence = f"значение пустое (строка {p.target_line} целевого файла)"
            else:
                continue
            findings.append(
                Finding(
                    key=p.key,
                    issue_type=self.issue_type,
                    severity=Severity.HIGH,
                    source=p.source,
                    target=p.target or "",
                    evidence=evidence,
                    confidence=1.0,
                )
            )
        return findings
