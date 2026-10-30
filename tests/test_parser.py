import json

import pytest

from locqa.arb import parse_arb, parse_arb_text
from locqa.errors import InputError


def test_reads_all_members_in_order(src_doc):
    keys = [m.key for m in src_doc.members]
    assert keys[:3] == ["@@locale", "appTitle", "okButton"]
    assert keys.count("@@comment") == 3
    assert keys[-2:] == ["dupKey", "dupKey"]


def test_repeated_comments_define_sections(src_doc):
    strings = src_doc.strings()
    assert strings["appTitle"].section is None  # before the first @@comment
    assert strings["menuPlay"].section == "MENU"
    assert strings["shopBuy"].section == "SHOP"
    assert strings["profileTitle"].section == "PROFILE"
    assert [c.value for c in src_doc.comments()] == ["MENU", "SHOP", "PROFILE"]


def test_json_load_would_lose_sections(fixtures):
    # Documents why the custom parser exists.
    data = json.loads((fixtures / "src_ru.arb").read_text(encoding="utf-8"))
    assert data["@@comment"] == "PROFILE"


def test_line_numbers(src_doc):
    lines = (src_doc.text).split("\n")
    for entry in src_doc.members:
        assert f'"{entry.key}"' in lines[entry.line - 1]


def test_strings_exclude_metadata_and_count(src_doc):
    strings = src_doc.strings()
    assert "@greeting" not in strings
    assert "@@comment" not in strings
    assert len(strings) == 24


def test_metadata_multiline_object(src_doc):
    meta = src_doc.metadata()
    assert meta["greeting"]["placeholders"]["name"]["type"] == "String"
    assert src_doc.locale() == "ru"


def test_escapes_decoded_and_raw_preserved(src_doc):
    strings = src_doc.strings()
    assert strings["shopNote"].value == "Цена: <g>{price}</g>\nСкидка: {discount}%"
    assert strings["shopNote"].raw == '"Цена: <g>{price}</g>\\nСкидка: {discount}%"'
    assert strings["quoteLine"].value == 'Нажмите "Купить"'
    assert strings["currencyIcon"].value == "\ue000"
    assert strings["currencyIcon"].raw == '"\\ue000"'


def test_duplicates_last_wins(tgt_doc):
    dups = tgt_doc.duplicates()
    assert list(dups) == ["dupKey"]
    assert [e.value for e in dups["dupKey"]] == ["Көшірме", "Қайталау"]
    assert tgt_doc.strings()["dupKey"].value == "Қайталау"


def test_empty_value_and_mixed_indent(tgt_doc):
    strings = tgt_doc.strings()
    assert strings["emptyInTarget"].value == ""
    assert strings["menuSettings"].value == "Баптаулар"


def test_raw_spans_match_text(tgt_doc):
    for m in tgt_doc.members:
        assert tgt_doc.text[m.start : m.end] == m.raw


def test_broken_file_reports_line(fixtures):
    with pytest.raises(InputError, match=r"строка 4"):
        parse_arb(fixtures / "broken.arb")


def test_missing_file(tmp_path):
    with pytest.raises(InputError, match="не найден"):
        parse_arb(tmp_path / "nope.arb")


@pytest.mark.parametrize(
    "text",
    [
        "[]",
        '{"a": 1}',
        '{"a": "x"} trailing',
        '{"a": "x",}',
        "",
    ],
)
def test_invalid_documents(text):
    with pytest.raises(InputError):
        parse_arb_text(text)


def test_empty_object_and_bom():
    assert parse_arb_text("{}").members == []
    doc = parse_arb_text('﻿{"a": "b"}')
    assert doc.strings()["a"].value == "b"


def test_crlf_offsets():
    text = '{\r\n  "a": "x",\r\n  "b": "y"\r\n}\r\n'
    doc = parse_arb_text(text)
    assert doc.strings()["b"].line == 3
    assert text[doc.strings()["b"].start : doc.strings()["b"].end] == '"y"'
