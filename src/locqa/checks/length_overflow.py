from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from locqa.arb.align import Pair
from locqa.checks.base import Check, CheckContext
from locqa.checks.registry import register
from locqa.models import Finding, IssueType, Severity
from locqa.text import WORD_RE

_TAG_RE = re.compile(r"<[^<>]*>")
_ARG_RE = re.compile(r"\{[^{}]*\}")


def visible_length(text: str) -> int:
    """Characters a player sees: no tags, an argument counts as one character (its value is
    unknown but the same in source and target), whitespace runs collapsed."""
    text = _ARG_RE.sub("x", _TAG_RE.sub("", text))
    return len(" ".join(text.split()))


@dataclass
class _Candidate:
    pair: Pair
    src_len: int
    tgt_len: int
    is_ui: bool
    tail: str | None

    @property
    def ratio(self) -> float:
        return self.tgt_len / self.src_len


@register
class LengthOverflowCheck(Check):
    """A short UI string whose translation is several times longer than the source.
    Keys that look like buttons, tabs or headings get a lower threshold."""

    issue_type = IssueType.LENGTH_OVERFLOW

    def run(self, pairs: Sequence[Pair], ctx: CheckContext) -> list[Finding]:
        cfg = ctx.config
        ui_key = re.compile(cfg.length_ui_key_pattern)
        candidates = []
        for p in pairs:
            if not p.target or p.target.strip() == p.source.strip():
                continue
            src_len, tgt_len = visible_length(p.source), visible_length(p.target)
            if not 0 < src_len <= cfg.length_max_source_chars:
                continue
            extra, ratio = tgt_len - src_len, tgt_len / src_len
            is_ui = bool(ui_key.search(p.key))
            if (ratio >= cfg.length_ratio and extra >= cfg.length_min_extra_chars) or (
                is_ui and ratio >= cfg.length_ui_ratio and extra >= cfg.length_ui_min_extra_chars
            ):
                candidates.append(
                    _Candidate(p, src_len, tgt_len, is_ui, self._tail(p, cfg.length_tail_words))
                )

        tails = Counter(c.tail for c in candidates if c.tail)
        findings = []
        for c in candidates:
            repeated = c.tail is not None and tails[c.tail] > 1
            if c.ratio >= cfg.length_high_ratio or repeated:
                severity, confidence = Severity.HIGH, 0.95
            elif c.ratio >= cfg.length_ratio:
                severity, confidence = (Severity.HIGH, 0.9) if c.is_ui else (Severity.MEDIUM, 0.8)
            else:
                severity, confidence = Severity.LOW, 0.6
            evidence = f"{c.tgt_len} символов против {c.src_len} в исходнике (×{c.ratio:.1f})"
            if c.is_ui:
                evidence += ", ключ похож на кнопку, вкладку или заголовок"
            if repeated:
                evidence += (
                    f"; хвост «{c.tail}» отсутствует в исходнике и повторяется "
                    f"ещё в {tails[c.tail] - 1} таких строках"
                )
            findings.append(
                Finding(
                    key=c.pair.key,
                    issue_type=self.issue_type,
                    severity=severity,
                    source=c.pair.source,
                    target=c.pair.target or "",
                    evidence=evidence,
                    confidence=confidence,
                )
            )
        return findings

    @staticmethod
    def _tail(p: Pair, n: int) -> str | None:
        """Last n words of the target, if the target has more words than that."""
        words = [w.lower() for w in WORD_RE.findall(p.target or "")]
        if len(words) <= n:
            return None
        return " ".join(words[-n:])
