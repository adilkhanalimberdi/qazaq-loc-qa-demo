from dataclasses import replace

import pytest

from conftest import make_pair
from locqa.checks import CheckContext, available, get_checks
from locqa.checks.placeholder_mismatch import PlaceholderMismatchCheck
from locqa.checks.plural_mismatch import PluralMismatchCheck
from locqa.checks.same_as_source import SameAsSourceCheck
from locqa.checks.suffix_harmony import SuffixHarmonyCheck
from locqa.checks.untranslated import UntranslatedCheck
from locqa.checks.wrong_language import WrongLanguageCheck
from locqa.config import Config
from locqa.errors import InputError
from locqa.models import IssueType, Severity

CTX = CheckContext(source_lang="ru", target_lang="kk")


def run(check, *pairs, ctx=CTX):
    return check.run(list(pairs), ctx)


# --- registry ---------------------------------------------------------------


def test_registry_lists_checks_in_issue_type_order():
    assert available() == [
        "untranslated",
        "same_as_source",
        "placeholder_mismatch",
        "plural_mismatch",
        "glossary_violation",
        "length_overflow",
        "inconsistent_term",
        "suffix_harmony",
        "orthography",
        "wrong_language",
    ]


def test_only_and_skip():
    assert [c.name for c in get_checks(only=["untranslated"])] == ["untranslated"]
    assert "same_as_source" not in [c.name for c in get_checks(skip=["same_as_source"])]


def test_unknown_check_name():
    with pytest.raises(InputError, match="nope"):
        get_checks(only=["nope"])
    with pytest.raises(InputError):
        get_checks(skip=["nope"])


# --- untranslated -----------------------------------------------------------


def test_untranslated_missing_and_empty():
    findings = run(
        UntranslatedCheck(),
        make_pair("Играть", None, key="a"),
        make_pair("Играть", "   ", key="b"),
    )
    assert [(f.key, f.target) for f in findings] == [("a", ""), ("b", "   ")]
    assert all(f.severity == Severity.HIGH and f.confidence == 1.0 for f in findings)
    assert "нет в целевом" in findings[0].evidence
    assert "пустое" in findings[1].evidence


def test_untranslated_not_found():
    assert run(UntranslatedCheck(), make_pair("Играть", "Ойнау")) == []


def test_untranslated_empty_source_is_ignored():
    assert run(UntranslatedCheck(), make_pair("", ""), make_pair(" ", None)) == []


# --- placeholder_mismatch ---------------------------------------------------


def test_placeholder_typo_found():
    [f] = run(PlaceholderMismatchCheck(), make_pair("Привет, {name}!", "Сәлем, {nam}!"))
    assert f.issue_type == IssueType.PLACEHOLDER_MISMATCH
    assert f.severity == Severity.HIGH
    assert "{name}" in f.evidence and "{nam}" in f.evidence


def test_placeholder_reordered_is_fine():
    assert run(PlaceholderMismatchCheck(), make_pair("{a} из {b}", "{b} ішінен {a}")) == []


def test_placeholder_duplicate_count_matters_for_simple_strings():
    [f] = run(PlaceholderMismatchCheck(), make_pair("{a} и {a}", "{a}"))
    assert "нет {a}" in f.evidence


def test_placeholder_plural_branches_compare_names_only():
    src = "{count, plural, one{{count} предмет} few{{count} предмета} other{{count} предметов}}"
    tgt = "{count, plural, other{{count} зат}}"
    assert run(PlaceholderMismatchCheck(), make_pair(src, tgt)) == []


def test_tags_and_newlines():
    [f] = run(PlaceholderMismatchCheck(), make_pair("<g>{p}</g>\nx", "{p} x"))
    assert f.severity == Severity.MEDIUM
    assert "<g>" in f.evidence and "переносы" in f.evidence

    # Reflowed lines alone are not reported by default...
    assert run(PlaceholderMismatchCheck(), make_pair("a\nb", "a b")) == []
    # ...but can be enabled.
    ctx = CheckContext(
        source_lang="ru", target_lang="kk", config=Config(report_newline_mismatch=True)
    )
    [f] = run(PlaceholderMismatchCheck(), make_pair("a\nb", "a b"), ctx=ctx)
    assert f.severity == Severity.LOW


def test_placeholder_skips_untranslated():
    assert run(PlaceholderMismatchCheck(), make_pair("{a}", None), make_pair("{a}", "")) == []


# --- same_as_source ---------------------------------------------------------


def test_same_as_source_found_with_confidence_by_length():
    findings = run(
        SameAsSourceCheck(),
        make_pair("Добро пожаловать", " Добро пожаловать ", key="multi"),
        make_pair("Профиль", "Профиль", key="single"),
        make_pair("Напугать", "Напугать", key="verb"),
    )
    by_key = {f.key: f for f in findings}
    assert by_key["multi"].confidence == 0.9
    assert by_key["multi"].severity == Severity.MEDIUM
    # A single word is often a shared loanword...
    assert by_key["single"].confidence == 0.4
    assert by_key["single"].severity == Severity.LOW
    # ...unless it carries Russian inflection.
    assert by_key["verb"].severity == Severity.MEDIUM
    assert "-ть" in by_key["verb"].evidence


def test_same_as_source_not_found_when_translated():
    assert run(SameAsSourceCheck(), make_pair("Играть", "Ойнау")) == []


@pytest.mark.parametrize("text", ["1 000", "{count}", "%", "<g>{n}</g> 50", "\ue000", "Super Shop"])
def test_same_as_source_legitimate_matches(text):
    # numbers, placeholders, symbols, private-use icons, Latin brands
    assert (
        run(
            SameAsSourceCheck(),
            make_pair("Начать новую игру", "Жаңа ойын бастау", key="ctx"),
            make_pair(text, text),
        )
        == []
    )


def test_same_as_source_allowlist():
    ctx = CheckContext(
        source_lang="ru",
        target_lang="kk",
        config=Config(same_as_source_allow_keys={"k1"}, same_as_source_allow_texts={"Бонус"}),
    )
    pairs = [make_pair("Профиль", "Профиль", key="k1"), make_pair("Бонус", "Бонус", key="k2")]
    assert run(SameAsSourceCheck(), *pairs, ctx=ctx) == []


def test_same_as_source_latin_source_still_flags_latin():
    # Universality: with a Latin-script source the brand exemption must not hide everything.
    findings = run(SameAsSourceCheck(), make_pair("Play now", "Play now"))
    assert len(findings) == 1


# --- plural_mismatch --------------------------------------------------------

RU_PLURAL = "{n, plural, one{{n} день} few{{n} дня} many{{n} дней} other{{n} дня}}"


def test_plural_valid_target_with_fewer_categories():
    # Kazakh has only one/other: dropping few/many is correct, not an error.
    assert run(PluralMismatchCheck(), make_pair(RU_PLURAL, "{n, plural, other{{n} күн}}")) == []


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("{n, plural, one{{n} күн}}", "нет обязательной ветки other"),
        ("{n, plural, one{{n} күн} other{{n} күн}", "ICU-синтаксис перевода сломан"),
        ("{n} күн", "в переводе нет {n, plural"),
        ("{n, select, other{{n} күн}}", "тип select вместо plural"),
    ],
)
def test_plural_broken_target_is_high(target, expected):
    [f] = run(PluralMismatchCheck(), make_pair(RU_PLURAL, target))
    assert f.severity == Severity.HIGH and f.confidence == 1.0
    assert expected in f.evidence


def test_plural_empty_branch_and_foreign_category():
    target = "{n, plural, one{} few{{n}} other{{n} күн}}"
    [f] = run(PluralMismatchCheck(), make_pair(RU_PLURAL, target))
    assert f.severity == Severity.MEDIUM
    assert "пустые ветки one" in f.evidence
    assert "категорий few нет" in f.evidence


def test_plural_categories_follow_target_language():
    # few is legitimate in a Russian target: the check is not tied to Kazakh.
    src = "{n, plural, one{{n} day} other{{n} days}}"
    ru = CheckContext(source_lang="en", target_lang="ru")
    assert run(PluralMismatchCheck(), make_pair(src, RU_PLURAL), ctx=ru) == []
    # Unknown language: categories are not checked, structure still is.
    xx = CheckContext(source_lang="en", target_lang="xx")
    assert run(PluralMismatchCheck(), make_pair(src, RU_PLURAL), ctx=xx) == []


def test_select_lost_variants():
    src = "{g, select, male{Он} female{Она} other{Они}}"
    [f] = run(PluralMismatchCheck(), make_pair(src, "{g, select, other{Ол}}"))
    assert f.severity == Severity.MEDIUM and "female, male" in f.evidence


def test_plural_ignores_plain_strings_and_broken_source():
    assert run(PluralMismatchCheck(), make_pair("Играть", "Ойнау")) == []
    assert (
        run(PluralMismatchCheck(), make_pair("{n, plural, one{x}", "{n, plural, other{y}}")) == []
    )


# --- suffix_harmony ---------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "written", "variants"),
    [
        ("{name}-ға сыйлық жіберу", "{name}-ға", "-ға/-ге/-қа/-ке"),
        ("{name}ге жіберілді", "{name}ге", "-ға/-ге"),
        ("{max}-нан көп", "{max}-нан", "-дан/-ден"),
        ("{n}-ші орын", "{n}-ші", "-ыншы"),
        ("{city}дағы үй", "{city}дағы", "-дағы/-дегі"),
        ("{team}ларымызға", "{team}ларымызға", "-ға/-ге"),
    ],
)
def test_suffix_after_placeholder_found(target, written, variants):
    [f] = run(SuffixHarmonyCheck(), make_pair("x {name}", target))
    assert f.issue_type == IssueType.SUFFIX_HARMONY
    assert written in f.evidence and variants in f.evidence


@pytest.mark.parametrize(
    "target",
    [
        "{place}-орында тұр",  # "орын" is a word, not a suffix
        "{n}-деңгей",  # a noun that starts like a suffix
        "{name} ойыншыға",  # the suffix is on the next word
        "Сәлем, {name}!",
    ],
)
def test_suffix_not_found(target):
    assert run(SuffixHarmonyCheck(), make_pair("x", target)) == []


def test_suffix_check_uses_target_language_profile():
    uz = CheckContext(source_lang="ru", target_lang="uz")
    [f] = run(SuffixHarmonyCheck(), make_pair("x", "{name}ga yuborish"), ctx=uz)
    assert "-ga/-ka/-qa" in f.evidence
    # A language without such suffixes yields nothing.
    en = CheckContext(source_lang="ru", target_lang="en")
    assert run(SuffixHarmonyCheck(), make_pair("x", "{name}-ға"), ctx=en) == []


# --- wrong_language ---------------------------------------------------------

KK_FILLER = [
    make_pair("Играть", "Ойнау", key="f1"),
    make_pair("Настройки", "Баптаулар", key="f2"),
]


def with_context(source, target, key="k", **context):
    return replace(make_pair(source, target, key=key), context=context)


def test_wrong_language_uzbek_by_markers():
    [f] = run(WrongLanguageCheck(), *KK_FILLER, make_pair("Начать игру", "O‘yinni boshlash"))
    assert f.severity == Severity.HIGH
    assert "uz" in f.evidence and "latin" in f.evidence


def test_wrong_language_matches_context_file():
    pair = with_context("Закрыть окно", "Oynani yopish", uz="Oynani yopish", en="Close window")
    [f] = run(WrongLanguageCheck(), *KK_FILLER, pair)
    assert f.confidence == 0.95 and "файла uz" in f.evidence


def test_wrong_language_english_copy_is_medium():
    pair = with_context("Открыто", "Unlocked", uz="Ochilgan", en="Unlocked")
    [f] = run(WrongLanguageCheck(), *KK_FILLER, pair)
    assert f.severity == Severity.MEDIUM


@pytest.mark.parametrize(
    "pair",
    [
        make_pair("Ваш ник: STARFOX", "Сіздің ник: STARFOX"),  # Latin carried from source
        make_pair("Кубок Night Drift", "Night Drift кубогы"),
        make_pair("НАБОР БЛЭК ВОЛВЗ", "BLACK WOLVES ЖИНАҒЫ"),  # capitalised title
        make_pair("Цена: %sGC", "%sGC"),  # printf specifier and abbreviation
        make_pair("Справка", "https://support.example.com/en/help"),
        with_context("Премиум", "Premium", uz="Premium", en="Premium"),  # same everywhere
        with_context("ур.", "lvl", en="lvl"),  # abbreviation
        make_pair("Battle Pass", "Battle Pass"),  # same_as_source territory
    ],
)
def test_wrong_language_not_found(pair):
    assert run(WrongLanguageCheck(), *KK_FILLER, pair) == []


def test_wrong_language_latin_target_file():
    # Universality: in a Latin-script target, Cyrillic text is the foreign one.
    ctx = CheckContext(source_lang="ru", target_lang="uz")
    pairs = [
        make_pair("Играть", "O‘ynash", key="a"),
        make_pair("Настройки", "Sozlamalar", key="b"),
        make_pair("Купить", "Сатып алу", key="c"),
    ]
    [f] = run(WrongLanguageCheck(), *pairs, ctx=ctx)
    assert f.key == "c" and "cyrillic" in f.evidence


def test_wrong_language_context_file_may_itself_be_wrong():
    # Checking the Uzbek file with the Kazakh file as context: the Kazakh file contains the
    # same Uzbek string by mistake, but the Uzbek string is in the right place here.
    ctx = CheckContext(source_lang="ru", target_lang="uz")
    pairs = [
        make_pair("Играть", "O‘ynash", key="a"),
        make_pair("Настройки", "Sozlamalar", key="b"),
        with_context("Закрыть окно", "Oynani yopish", key="c", kk="Oynani yopish", en="Close"),
    ]
    assert run(WrongLanguageCheck(), *pairs, ctx=ctx) == []
