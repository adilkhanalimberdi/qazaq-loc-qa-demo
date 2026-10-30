"""Per-language knowledge used by checks. A language without a profile still works:
checks that need the profile skip their language-specific part."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LanguageProfile:
    # CLDR cardinal plural categories (plural branches other than =N literals).
    plural_categories: frozenset[str]
    # Full-match regex for a run of inflectional suffixes whose form depends on the last
    # sound of the preceding word. None: the language does not attach such suffixes.
    harmonic_suffix: re.Pattern[str] | None = None
    # Interchangeable forms of one suffix, used in evidence: "-ға/-ге/-қа/-ке".
    suffix_variants: tuple[tuple[str, ...], ...] = ()
    # Letters or patterns that identify this language among others written in the same script.
    markers: re.Pattern[str] | None = None
    common_words: frozenset[str] = field(default_factory=frozenset)
    # Language-specific letter -> the letter of a related alphabet typed instead of it
    # on a keyboard without the layout (Kazakh қ typed as Russian к).
    lookalikes: dict[str, str] = field(default_factory=dict)
    # Word endings that mark a word as inflected in this language, so it cannot be an
    # international loanword shared with another language ("-ться", "-ые").
    inflection: re.Pattern[str] | None = None


def _alt(*forms: str) -> str:
    # Longest first, so the regex engine tries "ның" before "н".
    return "|".join(sorted(forms, key=len, reverse=True))


_KK_PLURAL = ("лар", "лер", "дар", "дер", "тар", "тер")
_KK_POSSESSIVE = (
    "ым", "ім", "м", "ың", "ің", "ң", "ы", "і", "сы", "сі",
    "ымыз", "іміз", "мыз", "міз", "ыңыз", "іңіз", "ңыз", "ңіз",
)  # fmt: skip
_KK_CASES = (
    ("ға", "ге", "қа", "ке", "на", "не", "а", "е"),
    ("ның", "нің", "дың", "дің", "тың", "тің"),
    ("ны", "ні", "ды", "ді", "ты", "ті", "н"),
    ("да", "де", "та", "те", "нда", "нде"),
    ("дағы", "дегі", "тағы", "тегі", "ндағы", "ндегі"),
    ("дан", "ден", "тан", "тен", "нан", "нен"),
    ("мен", "бен", "пен", "менен", "бенен", "пенен"),
)
_KK_ORDINAL = ("ыншы", "інші", "ншы", "нші", "шы", "ші")
_KK_SUFFIX_RE = re.compile(
    rf"(?:(?:{_alt(*_KK_PLURAL)})?(?:{_alt(*_KK_POSSESSIVE)})?"
    rf"(?:{_alt(*(f for group in _KK_CASES for f in group))})?|{_alt(*_KK_ORDINAL)})",
    re.IGNORECASE,
)

_UZ_CASES = (("ga", "ka", "qa"), ("ning",), ("ni",), ("da", "ta"), ("dan", "tan"))
_UZ_SUFFIX_RE = re.compile(
    rf"(?:lar)?(?:{_alt(*(f for group in _UZ_CASES for f in group))})", re.IGNORECASE
)

_TWO = frozenset({"one", "other"})

PROFILES: dict[str, LanguageProfile] = {
    "kk": LanguageProfile(
        plural_categories=_TWO,
        harmonic_suffix=_KK_SUFFIX_RE,
        suffix_variants=(*_KK_CASES, _KK_PLURAL, _KK_ORDINAL),
        markers=re.compile(r"[әғқңөұүһіӘҒҚҢӨҰҮҺІ]"),
        lookalikes=dict(zip("әғқңөұүһі", "агкноуухи", strict=True)),
    ),
    "uz": LanguageProfile(
        plural_categories=_TWO,
        harmonic_suffix=_UZ_SUFFIX_RE,
        suffix_variants=_UZ_CASES,
        # o‘ g‘ with any apostrophe-like sign (Latin), ў ҳ (Cyrillic, absent in Kazakh).
        markers=re.compile(r"[oOgG][‘’'ʻ`]|[ўҳЎҲ]"),
        lookalikes=dict(zip("ўқғҳ", "укгх", strict=True)),
        common_words=frozenset(
            [
                "va",
                "uchun",
                "bilan",
                "yoki",
                "emas",
                "kerak",
                "sotib",
                "olish",
                "yangi",
                "barcha",
                "sizning",
                "xato",
                "xatosi",
                "qilish",
                "bo‘lish",
                "hisob",
                "o‘yin",
            ]
        ),
    ),
    "ru": LanguageProfile(
        plural_categories=frozenset({"one", "few", "many", "other"}),
        # Verbs, adjectives, plurals and soft-sign forms that Kazakh never borrows as is.
        inflection=re.compile(
            r"(?:ться|тся|ть|ешь|ете|ите|ый|ий|ой|ая|яя|ое|ее|ые|ие|ых|их|ого|его|ому"
            r"|ами|ями|ов|ей|ья|ьи|ки|ги|хи|ры|ны|сы|ты|ды|лы|мы)$",
            re.IGNORECASE,
        ),
    ),
    "uk": LanguageProfile(plural_categories=frozenset({"one", "few", "many", "other"})),
    "en": LanguageProfile(plural_categories=_TWO),
    "es": LanguageProfile(plural_categories=frozenset({"one", "many", "other"})),
    "pt": LanguageProfile(plural_categories=frozenset({"one", "many", "other"})),
}


def subtag(locale: str) -> str:
    """Language subtag of a locale: kk_KZ -> kk, pt-BR -> pt."""
    return re.split(r"[_-]", locale, maxsplit=1)[0].lower()


def profile(lang: str) -> LanguageProfile | None:
    """Profile for a locale such as kk, kk_KZ or pt-BR."""
    return PROFILES.get(subtag(lang))
