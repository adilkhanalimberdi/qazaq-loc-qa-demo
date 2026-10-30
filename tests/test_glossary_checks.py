import pytest

from conftest import make_pair
from locqa.checks import CheckContext
from locqa.checks.glossary_violation import GlossaryViolationCheck
from locqa.checks.inconsistent_term import InconsistentTermCheck
from locqa.glossary import Glossary, GlossaryTerm
from locqa.models import Severity


def term(ru, kk, **kw):
    return GlossaryTerm(ru=ru, kk=kk, en="", note="", **kw)


def ctx_with(*terms):
    return CheckContext(source_lang="ru", target_lang="kk", glossary=Glossary(list(terms)))


def run(check, *pairs, ctx):
    return check.run(list(pairs), ctx)


# --- term matching ----------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "found"),
    [
        ("Получите награды", "награды"),
        ("НАГРАДА ДНЯ", "НАГРАДА"),
        ("Наградной фонд", "Наградной"),  # same stem
        ("Играть", None),
    ],
)
def test_ru_stem_matching(source, found):
    assert term("награда", "сыйлық").find_in_source(source) == found


def test_ru_forms_are_whole_words():
    t = term("приз", "жүлде", ru_forms=("приз", "призы", "призов"))
    assert t.find_in_source("Ценные призы") == "призы"
    assert t.find_in_source("Призрак") is None
    # A short lemma without forms matches only itself, not every word it starts.
    assert term("дом", "үй").find_in_source("Домино") is None


@pytest.mark.parametrize(
    ("target", "matches"),
    [
        ("Сыйлығын алыңыз", True),  # қ -> ғ before a vowel suffix
        ("СЫЙЛЫҚТАР", True),
        ("Жүлде", False),
        ("Көлігіңіз дайын", True),
    ],
)
def test_kk_suffixes_and_consonant_alternation(target, matches):
    t = term("x", "сыйлық|көлік")
    assert bool(t.kk_regex.search(target)) is matches


def test_latin_kk_variant_is_a_whole_word():
    t = term("Grand Coins", "GC")
    assert t.kk_regex.search("250 GC")
    assert t.kk_regex.search("GC-ге")
    assert not t.kk_regex.search("GCX")


# --- glossary_violation -----------------------------------------------------

FAMILY = term("семья", "отбасы", forbidden_kk=("жанұя",), ru_forms=("семья", "семьи", "семью"))


def test_glossary_forbidden_variant():
    [f] = run(
        GlossaryViolationCheck(), make_pair("Состав семьи", "Жанұя құрамы"), ctx=ctx_with(FAMILY)
    )
    assert f.confidence == 0.95 and f.severity == Severity.MEDIUM
    assert "«Жанұя»" in f.evidence and "«отбасы»" in f.evidence


def test_glossary_missing_term():
    [f] = run(
        GlossaryViolationCheck(),
        make_pair("Баланс", "Тек ақша қалды"),
        ctx=ctx_with(term("баланс", "баланс")),
    )
    assert f.confidence == 0.7 and "в переводе нет «баланс»" in f.evidence


def test_glossary_term_present_or_absent_in_source():
    ctx = ctx_with(FAMILY)
    assert (
        run(GlossaryViolationCheck(), make_pair("Распустить семью", "Отбасын тарату"), ctx=ctx)
        == []
    )
    assert run(GlossaryViolationCheck(), make_pair("Играть", "Ойнау"), ctx=ctx) == []


def test_glossary_slang_and_long_descriptions_are_softer():
    slang = term("варн", "варн|ескерту", register="slang", severity=Severity.LOW)
    [f] = run(
        GlossaryViolationCheck(), make_pair("Вы получили варн", "Сізге айып"), ctx=ctx_with(slang)
    )
    assert f.severity == Severity.LOW and f.confidence < 0.7
    long_src = "Соберите всю семью вместе и пройдите испытание до конца недели"
    [f] = run(
        GlossaryViolationCheck(),
        make_pair(long_src, "Бәрін жинап, сынақтан өтіңіз"),
        ctx=ctx_with(FAMILY),
    )
    assert f.severity == Severity.LOW


def test_glossary_without_glossary_or_kk_does_nothing():
    plain = CheckContext(source_lang="ru", target_lang="kk")
    assert run(GlossaryViolationCheck(), make_pair("Баланс", "Ақша"), ctx=plain) == []
    undecided = ctx_with(term("выговор", ""))
    assert run(GlossaryViolationCheck(), make_pair("Выговор", "Айыптау"), ctx=undecided) == []


# --- inconsistent_term ------------------------------------------------------

CTX = CheckContext(source_lang="ru", target_lang="kk")


def test_inconsistent_minority_translation():
    pairs = [
        make_pair("Награды", "Сыйлықтар", key="a"),
        make_pair("Награды", "сыйлықтар", key="b"),
        make_pair("Награды", "СЫЙЛЫҚТАРЫ", key="c"),  # inflection only: same reference
        make_pair("Награды", "Марапаттар", key="d"),
    ]
    [f] = run(InconsistentTermCheck(), *pairs, ctx=CTX)
    assert f.key == "d" and f.suggestion == "Сыйлықтар"
    assert f.severity == Severity.MEDIUM and "в 3 других ключах" in f.evidence


@pytest.mark.parametrize(
    "pairs",
    [
        # inflection differences only
        [make_pair("Качество", "Сапа", key="a"), make_pair("Качество", "Сапасы", key="b")],
        # a tie: no reference translation
        [make_pair("Хорошо", "Жарайды", key="a"), make_pair("Хорошо", "Жақсы", key="b")],
        # too short to be unambiguous
        [make_pair("От", "Кімнен", key=k) for k in "ab"] + [make_pair("От", "Кемінде", key="c")],
        # a phrase, not a term
        [
            make_pair("Нажмите здесь чтобы начать игру", t, key=k)
            for k, t in [("a", "Ойынды жүктеу"), ("b", "Ойынды жүктеу"), ("c", "Басыңыз")]
        ],
    ],
)
def test_inconsistent_not_found(pairs):
    assert run(InconsistentTermCheck(), *pairs, ctx=CTX) == []
