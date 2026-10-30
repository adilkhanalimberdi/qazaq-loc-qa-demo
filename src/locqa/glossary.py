"""glossary.csv loader and term matching.

A term matches by word stem, so inflected forms count: Russian "семьи", "семью" match
"семья"; Kazakh "сыйлығын" matches "сыйлық" (final к/қ/п alternate with г/ғ/б).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from locqa.errors import InputError
from locqa.models import Severity

REQUIRED_COLUMNS = ("ru", "kk", "en", "note")
OPTIONAL_COLUMNS = ("register", "forbidden_kk", "severity", "ru_forms")
REGISTERS = ("literary", "slang")


_RU_ENDING = re.compile(r"(?:ость|ия|ья|ие|ье|[аяоеёьйыиу])$", re.IGNORECASE)
_KK_ALTERNATION = {"к": "[кг]", "қ": "[қғ]", "п": "[пб]"}
_MIN_STEM = 4


def _ru_form_pattern(form: str) -> str:
    """A Russian form as a regex: a stem followed by any ending, or the exact word if the
    stem would be too short ("дом" must not match "домино"); list such forms in ru_forms."""
    words = form.split()
    last = words[-1]
    stem = _RU_ENDING.sub("", last)
    if len(stem) < _MIN_STEM or not re.search(r"[а-яё]", last, re.IGNORECASE):
        tail = re.escape(last) + r"\b"
    else:
        tail = re.escape(stem) + r"\w*"
    return r"\b" + r"\s+".join([*map(re.escape, words[:-1]), tail])


def _kk_form_pattern(form: str) -> str:
    """A Kazakh form as a regex: the form plus any suffixes, with the final consonant
    alternation of Kazakh (көлік -> көлігі). Non-Cyrillic forms (GC) match as whole words,
    optionally with a hyphenated suffix (GC-ге)."""
    words = form.split()
    last = words[-1]
    if not re.search(r"[а-яёәғқңөұүһі]", last, re.IGNORECASE):
        tail = re.escape(last) + r"(?![^\W_])"
    else:
        head, final = last[:-1], last[-1:]
        tail = re.escape(head) + _KK_ALTERNATION.get(final.lower(), re.escape(final)) + r"\w*"
    return r"(?<!\w)" + r"\s+".join([*map(re.escape, words[:-1]), tail])


def _compile(patterns: list[str]) -> re.Pattern[str] | None:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE) if patterns else None


@dataclass(frozen=True)
class GlossaryTerm:
    ru: str
    kk: str  # allowed translations separated by "|"; empty: not decided yet
    en: str
    note: str
    register: str = "literary"
    forbidden_kk: tuple[str, ...] = ()
    severity: Severity = Severity.MEDIUM
    # Exact source word forms to look for; default: any word with the stem of `ru`.
    ru_forms: tuple[str, ...] = ()

    @property
    def kk_variants(self) -> tuple[str, ...]:
        return tuple(v.strip() for v in self.kk.split("|") if v.strip())

    @cached_property
    def ru_regex(self) -> re.Pattern[str] | None:
        if self.ru_forms:
            # Listed forms are whole words: "приз" must not match "призрак".
            forms = sorted(self.ru_forms, key=len, reverse=True)
            return _compile([r"\b" + r"\s+".join(map(re.escape, f.split())) + r"\b" for f in forms])
        return _compile([_ru_form_pattern(self.ru)])

    @cached_property
    def kk_regex(self) -> re.Pattern[str] | None:
        return _compile([_kk_form_pattern(v) for v in self.kk_variants])

    @cached_property
    def forbidden_regex(self) -> re.Pattern[str] | None:
        return _compile([_kk_form_pattern(v) for v in self.forbidden_kk])

    def find_in_source(self, text: str) -> str | None:
        m = self.ru_regex.search(text) if self.ru_regex else None
        return m.group() if m else None


@dataclass
class Glossary:
    terms: list[GlossaryTerm]


def load_glossary(path: Path) -> Glossary:
    path = Path(path)
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames or []
            missing = [c for c in REQUIRED_COLUMNS if c not in columns]
            if missing:
                raise InputError(f"{path}: в глоссарии нет колонок: {', '.join(missing)}")
            terms = [_row_to_term(row, path, n) for n, row in enumerate(reader, start=2)]
    except FileNotFoundError as e:
        raise InputError(f"файл не найден: {path}") from e
    except UnicodeDecodeError as e:
        raise InputError(f"{path}: файл не в UTF-8") from e
    return Glossary(terms=[t for t in terms if t.ru])


def _row_to_term(row: dict[str, str | None], path: Path, line: int) -> GlossaryTerm:
    def cell(name: str) -> str:
        return (row.get(name) or "").strip()

    register = cell("register") or "literary"
    if register not in REGISTERS:
        raise InputError(
            f"{path}:{line}: register должен быть literary или slang, а не '{register}'"
        )
    severity = cell("severity") or Severity.MEDIUM.value
    try:
        sev = Severity(severity)
    except ValueError as e:
        raise InputError(f"{path}:{line}: неизвестная severity '{severity}'") from e
    forbidden = tuple(v.strip() for v in cell("forbidden_kk").split("|") if v.strip())
    ru_forms = tuple(v.strip() for v in cell("ru_forms").split("|") if v.strip())
    return GlossaryTerm(
        ru=cell("ru"),
        kk=cell("kk"),
        en=cell("en"),
        note=cell("note"),
        register=register,
        forbidden_kk=forbidden,
        severity=sev,
        ru_forms=ru_forms,
    )
