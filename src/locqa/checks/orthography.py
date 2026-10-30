from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from locqa import langs
from locqa.arb.align import Pair
from locqa.checks.base import Check, CheckContext
from locqa.checks.registry import register
from locqa.checks.same_as_source import script_of
from locqa.models import Finding, IssueType, Severity
from locqa.text import WORD_RE, mask_markup, match_case

# Latin letters that look like Cyrillic ones, and back. Kazakh і is the Latin i lookalike.
_LAT_TO_CYR = dict(zip("aceopxyiABCEHKMOPTX", "асеорхуіАВСЕНКМОРТХ", strict=True))
_CYR_TO_LAT = {c: lat for lat, c in _LAT_TO_CYR.items()} | {"к": "k", "К": "K"}

# Kazakh 2nd and 3rd person possessives differ only by ң/н near the end of a word
# (деңгейің / деңгейін); both are correct, so such pairs are not typos.
_GRAMMATICAL_TAIL = 4


@dataclass
class _Issue:
    word: str
    fix: str
    severity: Severity
    confidence: float
    text: str


def _mixed_script_fix(word: str) -> tuple[str, list[str]] | None:
    """For a word mixing Latin and Cyrillic letters: the word in its majority script and
    the foreign letters, or None if the word is in one script."""
    scripts = Counter(script_of(ch) for ch in word)
    if scripts.keys() != {"LATIN", "CYRILLIC"}:
        return None
    main = "CYRILLIC" if scripts["CYRILLIC"] >= scripts["LATIN"] else "LATIN"
    table = _LAT_TO_CYR if main == "CYRILLIC" else _CYR_TO_LAT
    foreign = [ch for ch in word if script_of(ch) != main]
    if not all(ch in table for ch in foreign):
        return None  # a real foreign letter, not a lookalike: not a typo of this kind
    return "".join(table.get(ch, ch) if script_of(ch) != main else ch for ch in word), foreign


class _Vocabulary:
    """Word frequencies of the target file, grouped by the form with lookalikes replaced."""

    def __init__(self, pairs: Sequence[Pair], lookalikes: dict[str, str]) -> None:
        self.table = str.maketrans(lookalikes)
        self.lookalikes = lookalikes
        self.freq: Counter[str] = Counter()
        for p in pairs:
            if p.target and p.target.strip() != p.source.strip():
                self.freq.update(w.lower() for w in WORD_RE.findall(mask_markup(p.target)))
        self.groups: dict[str, list[str]] = {}
        for w in self.freq:
            self.groups.setdefault(w.translate(self.table), []).append(w)

    def _degraded(self, word: str, correct: str) -> bool:
        """`word` is `correct` with some language-specific letters typed as lookalikes,
        and nothing else changed."""
        diffs = [i for i, (a, b) in enumerate(zip(word, correct, strict=True)) if a != b]
        if not diffs or any(self.lookalikes.get(correct[i]) != word[i] for i in diffs):
            return False
        tail = len(word) - _GRAMMATICAL_TAIL
        return not all(correct[i] == "ң" and i >= tail for i in diffs)

    def best_form(self, word: str) -> tuple[str, int] | None:
        """The more frequent correct spelling of `word` and its count, if any."""
        lower = word.lower()
        options = [
            v
            for v in self.groups.get(lower.translate(self.table), ())
            if v != lower and self._degraded(lower, v) and self.freq[v] >= self.freq[lower]
        ]
        if not options:
            return None
        best = max(options, key=lambda v: self.freq[v])
        return best, self.freq[best]


@register
class OrthographyCheck(Check):
    """Lookalike letters: Latin letters inside Cyrillic words (and back), and language
    letters typed as their nearest Russian analogue (қ -> к) when the correct spelling
    occurs in the same file at least as often."""

    issue_type = IssueType.ORTHOGRAPHY

    def run(self, pairs: Sequence[Pair], ctx: CheckContext) -> list[Finding]:
        cfg = ctx.config
        profile = langs.profile(ctx.target_lang)
        vocab = _Vocabulary(pairs, profile.lookalikes) if profile and profile.lookalikes else None
        findings = []
        for p in pairs:
            if not p.target or p.target.strip() == p.source.strip():
                continue  # reported as same_as_source
            issues = []
            for m in WORD_RE.finditer(mask_markup(p.target)):
                word = m.group()
                mixed = _mixed_script_fix(word)
                if mixed:
                    fix, foreign = mixed
                    issues.append(
                        _Issue(
                            word,
                            fix,
                            Severity.MEDIUM,
                            0.95,
                            f"«{word}»: буквы {' '.join(foreign)} из другого алфавита",
                        )
                    )
                    continue
                if vocab is None or len(word) < cfg.orthography_min_word_len:
                    continue
                found = vocab.best_form(word)
                if not found:
                    continue
                best, count = found
                own = vocab.freq[word.lower()]
                if count >= cfg.orthography_strong_ratio * own:
                    severity, confidence = Severity.MEDIUM, 0.9
                elif count > own:
                    severity, confidence = Severity.MEDIUM, 0.75
                else:
                    severity, confidence = Severity.LOW, 0.6
                fix = match_case(best, word)
                issues.append(
                    _Issue(
                        word,
                        fix,
                        severity,
                        confidence,
                        f"«{word}» ({own}×) вместо «{fix}» ({count}× в файле)",
                    )
                )
            if not issues:
                continue
            suggestion = p.target
            for issue in issues:
                suggestion = suggestion.replace(issue.word, issue.fix, 1)
            findings.append(
                Finding(
                    key=p.key,
                    issue_type=self.issue_type,
                    severity=max((i.severity for i in issues), key=lambda s: s.rank),
                    source=p.source,
                    target=p.target,
                    evidence="; ".join(i.text for i in issues),
                    suggestion=suggestion,
                    confidence=max(i.confidence for i in issues),
                )
            )
        return findings
