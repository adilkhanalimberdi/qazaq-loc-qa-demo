from collections import Counter

import pytest

from locqa.arb import icu


def test_simple_arguments():
    assert icu.extract_arguments("Привет, {name}! У вас {count}") == Counter(name=1, count=1)


def test_plural_arguments_and_branches():
    msg = "{count, plural, =0{нет} one{{count} предмет у {name}} other{# предметов}}"
    nodes = icu.parse(msg)
    arg = nodes[0]
    assert isinstance(arg, icu.Argument)
    assert arg.type == "plural"
    assert set(arg.options) == {"=0", "one", "other"}
    assert isinstance(arg.options["other"][0], icu.Pound)
    assert icu.extract_arguments(msg) == Counter(count=2, name=1)
    assert icu.has_complex_argument(msg)


def test_select_and_offset():
    nodes = icu.parse("{g, select, male{он} female{она} other{они}} {n, plural, offset:1 other{#}}")
    args = list(icu.iter_arguments(nodes))
    assert [a.type for a in args] == ["select", "plural"]
    assert args[1].offset == 1


def test_typed_argument_with_style():
    arg = icu.parse("{price, number, currency}")[0]
    assert (arg.name, arg.type, arg.style) == ("price", "number", "currency")


@pytest.mark.parametrize(
    "msg",
    ["{name", "text }", "{}", "{n, plural, one{x}", "{n, plural, one{a} one{b}}", "{n,}"],
)
def test_syntax_errors(msg):
    with pytest.raises(icu.IcuSyntaxError):
        icu.parse(msg)


def test_broken_message_falls_back_to_regex():
    assert icu.extract_arguments("{name} и {count") == Counter(name=1)


def test_apostrophe_is_literal_by_default():
    # Flutter gen-l10n default (use-escaping: false): apostrophes are plain text.
    assert icu.extract_arguments("o'zbek {name}") == Counter(name=1)
    assert icu.extract_arguments("'{name}'") == Counter(name=1)
    assert icu.parse("'{name}'", use_escaping=True) == ["{name}"]


def test_tags_and_newlines():
    assert icu.extract_tags("<g>a</g> <font color=red>b</font>") == Counter(
        {"<g>": 1, "</g>": 1, "<font color=red>": 1, "</font>": 1}
    )
    assert icu.extract_tags("a < b > c") == Counter()
    assert icu.count_newlines("a\nb\n") == 2
