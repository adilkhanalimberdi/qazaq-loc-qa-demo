from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Sequence

from locqa.arb.align import Pair
from locqa.checks.base import Check, CheckContext
from locqa.checks.registry import register
from locqa.models import Finding, IssueType, Severity
from locqa.text import WORD_RE, mask_markup

# Comparing word stems hides inflection and possessives: "сапа" / "сапасы", "себеп" / "себебі".
_STEM_LEN = 4


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w{}\s]", " ", text).split()).casefold()


def _stems(text: str) -> frozenset[str]:
    return frozenset(w.casefold()[:_STEM_LEN] for w in WORD_RE.findall(mask_markup(text)))


@register
class InconsistentTermCheck(Check):
    """The same source text is translated with different words in different keys: the
    translation used by a clear majority is taken as the reference and the others are
    reported. Differences only in word endings are not reported."""

    issue_type = IssueType.INCONSISTENT_TERM

    def run(self, pairs: Sequence[Pair], ctx: CheckContext) -> list[Finding]:
        cfg = ctx.config
        groups: dict[str, list[Pair]] = defaultdict(list)
        for p in pairs:
            if p.target and p.target.strip() and _norm(p.target) != _norm(p.source):
                groups[_norm(p.source)].append(p)

        findings = []
        for source, group in groups.items():
            if (
                len(group) < 2
                or len(source) < cfg.inconsistent_min_source_chars
                or len(source.split()) > cfg.inconsistent_max_source_words
            ):
                continue  # too short to be unambiguous, or a phrase rather than a term
            by_stems: dict[frozenset[str], list[Pair]] = defaultdict(list)
            for p in group:
                by_stems[_stems(p.target or "")].append(p)
            if len(by_stems) < 2:
                continue  # only inflection differs
            ranked = sorted(by_stems.values(), key=len, reverse=True)
            majority = ranked[0]
            if len(majority) < cfg.inconsistent_min_majority or len(majority) == len(ranked[1]):
                continue  # no clear reference translation
            reference = Counter(p.target for p in majority).most_common(1)[0][0] or ""
            others = ", ".join(p.key for p in majority[:3]) + ("…" if len(majority) > 3 else "")
            for variant in ranked[1:]:
                for p in variant:
                    findings.append(
                        Finding(
                            key=p.key,
                            issue_type=self.issue_type,
                            severity=Severity.MEDIUM if len(majority) >= 3 else Severity.LOW,
                            source=p.source,
                            target=p.target or "",
                            evidence=(
                                f"тот же исходник в {len(majority)} других ключах ({others}) "
                                f"переведён как «{reference}», здесь другими словами"
                            ),
                            suggestion=reference,
                            confidence=0.8 if len(majority) >= 3 else 0.65,
                        )
                    )
        return findings
