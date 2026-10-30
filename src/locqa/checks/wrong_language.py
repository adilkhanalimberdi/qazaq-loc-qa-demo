from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from locqa import langs
from locqa.arb.align import Pair
from locqa.checks.base import Check, CheckContext
from locqa.checks.registry import register
from locqa.checks.same_as_source import dominant_script, letters, script_of
from locqa.models import Finding, IssueType, Severity
from locqa.text import MARKUP_RE as _MARKUP_RE
from locqa.text import WORD_RE as _WORD_RE

# Shorter words are mostly abbreviations: "lvl", "GC", "VIP".
_MIN_WORD_LEN = 4


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _foreign_words(target: str, carried: str) -> list[str]:
    """Words of the target that are not carried over from the source or the reference
    translations (brands, product names, nicknames). Arguments and tags are ignored."""
    known = {w.casefold() for w in _WORD_RE.findall(carried)}
    words = _WORD_RE.findall(_MARKUP_RE.sub(" ", target))
    return [w for w in words if len(w) >= _MIN_WORD_LEN and w.casefold() not in known]


def _file_script(texts: Sequence[str]) -> str | None:
    """Script of the file by string vote, so one long foreign paragraph cannot outweigh it."""
    votes = Counter(dominant_script([_MARKUP_RE.sub(" ", t)]) for t in texts)
    votes.pop(None, None)
    return votes.most_common(1)[0][0] if votes else None


def _guess_language(text: str, target_lang: str) -> str | None:
    words = {w.casefold() for w in _WORD_RE.findall(text)}
    for lang, prof in langs.PROFILES.items():
        if lang == target_lang or prof.markers is None:
            continue
        if prof.markers.search(text) or words & prof.common_words:
            return lang
    return None


@register
class WrongLanguageCheck(Check):
    """Text in another language: the translation is in a different script than the rest of
    the target file, or it equals a --context translation into another language."""

    issue_type = IssueType.WRONG_LANGUAGE

    def run(self, pairs: Sequence[Pair], ctx: CheckContext) -> list[Finding]:
        target_script = _file_script([p.target for p in pairs if p.target])
        target_lang = langs.subtag(ctx.target_lang)
        findings = []
        for p in pairs:
            if not p.target or not letters(p.target):
                continue
            if _norm(p.target) == _norm(p.source):
                continue  # reported as same_as_source
            others = {
                lang: text
                for lang, text in p.context.items()
                if langs.subtag(lang) != target_lang and letters(text)
            }
            finding = self._context_match(p, others, target_script) or self._script_mismatch(
                p, others, target_script, target_lang
            )
            if finding:
                findings.append(finding)
        return findings

    def _context_match(
        self, p: Pair, others: dict[str, str], target_script: str | None
    ) -> Finding | None:
        matched = sorted(lang for lang, text in others.items() if _norm(text) == _norm(p.target))
        if not matched or not _foreign_words(p.target, carried=""):
            return None  # no match, or only abbreviations and symbols: "lvl", "en"
        # The context file itself may be the wrong one (Uzbek text planted in the Kazakh file
        # also "matches" the Uzbek file): a match counts only if the text is in another script
        # than the target file or carries letters of the matched language.
        own_script = _file_script([p.target]) == target_script
        markers = [langs.profile(lang) for lang in matched]
        if own_script and not any(m and m.markers and m.markers.search(p.target) for m in markers):
            return None
        if len(matched) == len(others) and len(others) > 1:
            return None  # every language keeps it as is: a brand or a name
        lang = matched[0]
        if lang == "en" or (len(matched) > 1 and "en" in matched):
            # English left in place is often an accepted game term ("Battle Pass").
            severity, confidence = Severity.MEDIUM, 0.6
        else:
            severity, confidence = Severity.HIGH, 0.95
        return Finding(
            key=p.key,
            issue_type=self.issue_type,
            severity=severity,
            source=p.source,
            target=p.target,
            evidence=f"перевод совпадает со строкой из файла {', '.join(matched)}",
            confidence=confidence,
        )

    def _script_mismatch(
        self, p: Pair, others: dict[str, str], target_script: str | None, target_lang: str
    ) -> Finding | None:
        if target_script is None:
            return None
        carried = " ".join([p.source, *others.values()])
        words = _foreign_words(p.target, carried)
        foreign = [w for w in words if script_of(w[0]) != target_script]
        native = [w for w in words if script_of(w[0]) == target_script]
        foreign_letters = sum(len(w) for w in foreign)
        if foreign_letters < 3 or foreign_letters <= sum(len(w) for w in native):
            return None
        guess = _guess_language(" ".join(foreign), target_lang)
        if guess is None and all(w.isupper() for w in foreign):
            return None  # capitalised names and event titles: "BLACK WOLVES"
        script = script_of(foreign[0][0]).lower()
        evidence = f"{len(foreign)} сл. в алфавите {script} при основном {target_script.lower()}"
        if guess:
            evidence += f", похоже на язык {guess}"
        evidence += f": {' '.join(foreign[:6])}"
        return Finding(
            key=p.key,
            issue_type=self.issue_type,
            severity=Severity.HIGH,
            source=p.source,
            target=p.target,
            evidence=evidence,
            confidence=0.9 if guess or len(foreign) > 1 else 0.7,
        )
