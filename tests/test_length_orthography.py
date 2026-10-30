import pytest

from conftest import make_pair
from locqa.checks import CheckContext
from locqa.checks.length_overflow import LengthOverflowCheck, visible_length
from locqa.checks.orthography import OrthographyCheck
from locqa.models import Severity

CTX = CheckContext(source_lang="ru", target_lang="kk")


def run(check, *pairs, ctx=CTX):
    return check.run(list(pairs), ctx)


# --- length_overflow --------------------------------------------------------


def test_visible_length_ignores_tags_and_argument_values():
    assert visible_length("<g>{count}</g>  монет") == len("x монет")


def test_length_overflow_found_with_numbers_in_evidence():
    [f] = run(LengthOverflowCheck(), make_pair("Обмен", "Айырбастау бөліміне өту", key="swap"))
    assert f.severity == Severity.HIGH  # ×4.6 is above the high ratio
    assert "23 символов против 5" in f.evidence


def test_length_ui_key_has_lower_threshold():
    pair = ("Награды", "Сыйлықтарыңыз бар")  # ×2.4: normal for text, too long for a tab
    assert run(LengthOverflowCheck(), make_pair(*pair, key="rewardsText")) == []
    [f] = run(LengthOverflowCheck(), make_pair(*pair, key="rewardsTab"))
    assert f.severity == Severity.LOW and "вкладку" in f.evidence


def test_length_repeated_tail_raises_severity():
    pairs = [
        make_pair("Найти друзей", "Достарды табу үшін осы жерді басыңыз", key="a"),
        make_pair("Открыть карту", "Картаны ашу үшін осы жерді басыңыз", key="b"),
    ]
    findings = run(LengthOverflowCheck(), *pairs)
    assert len(findings) == 2
    assert all(f.severity == Severity.HIGH for f in findings)
    assert "хвост «осы жерді басыңыз»" in findings[0].evidence


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("Играть", "Ойнау"),
        ("Цели", "Мақсаттар"),  # ×2.25 but only 5 extra characters
        ("Это длинное описание, которое уже не кнопка", "x" * 200),  # source too long
        ("Ок", "Ок"),
    ],
)
def test_length_not_found(source, target):
    assert run(LengthOverflowCheck(), make_pair(source, target, key="okButton")) == []


# --- orthography ------------------------------------------------------------

VOCAB = [
    make_pair("Подарок", "Сыйлық", key="v1"),
    make_pair("Подарок дня", "Күн сыйлығы мен сыйлық", key="v2"),
    make_pair("Время", "Уақыт және сағат", key="v3"),
]


def test_orthography_russian_letter_instead_of_kazakh():
    [f] = run(OrthographyCheck(), *VOCAB, make_pair("Подарок в сундуке", "Сыйлык сандыққа түсті"))
    assert f.severity == Severity.MEDIUM and f.confidence == 0.75
    assert "«Сыйлык» (1×) вместо «Сыйлық» (2× в файле)" in f.evidence
    assert f.suggestion == "Сыйлық сандыққа түсті"


def test_orthography_keeps_upper_case_in_suggestion():
    [f] = run(OrthographyCheck(), *VOCAB, make_pair("Подарок", "СЫЙЛЫК"))
    assert f.suggestion == "СЫЙЛЫҚ"


def test_orthography_latin_lookalikes():
    [f] = run(OrthographyCheck(), make_pair("Нажмите", "Батырманы басыңыз, cосын ойнаңыз"))
    assert f.confidence == 0.95 and "буквы c" in f.evidence
    assert f.suggestion == "Батырманы басыңыз, сосын ойнаңыз"
    # Kazakh і typed as Latin i.
    [f] = run(OrthographyCheck(), make_pair("Уровень", "Деңгейiн"))
    assert f.suggestion == "Деңгейін"


@pytest.mark.parametrize(
    "target",
    [
        "Бас",  # бас and бәс are different words: бәс is not a degraded бас
        "Сіздің деңгейін",  # -ін vs -ің are both grammatical endings
        "Уақыт",  # no variant in the file
        "Super Shop",  # Latin brand, single script
        "Grand Mobile-де",  # Cyrillic suffix on a Latin word is not a lookalike
    ],
)
def test_orthography_not_found(target):
    pairs = [
        *VOCAB,
        make_pair("Ставка", "Бәс бәс бәс", key="v4"),
        make_pair("x", "Деңгейің", key="v5"),
    ]
    assert run(OrthographyCheck(), *pairs, make_pair("Источник", target)) == []


def test_orthography_without_language_profile_checks_only_lookalikes():
    ctx = CheckContext(source_lang="ru", target_lang="xx")
    assert run(OrthographyCheck(), *VOCAB, make_pair("x", "Сыйлык"), ctx=ctx) == []
    [f] = run(OrthographyCheck(), make_pair("x", "Пpивет"), ctx=ctx)
    assert f.suggestion == "Привет"
