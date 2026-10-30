import pytest

from locqa.arb import encode_json_string, parse_arb, parse_arb_text, replace_values, write_text


def _changed_lines(before: str, after: str) -> list[int]:
    a, b = before.split("\n"), after.split("\n")
    assert len(a) == len(b)
    return [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]


def test_no_changes_is_identity(fixtures, tmp_path):
    original = (fixtures / "tgt_kk.arb").read_bytes()
    doc = parse_arb(fixtures / "tgt_kk.arb")
    out = tmp_path / "out.arb"
    write_text(out, replace_values(doc, {}))
    assert out.read_bytes() == original


def test_single_change_touches_one_line_only(fixtures, tmp_path):
    original = (fixtures / "tgt_kk.arb").read_bytes()
    doc = parse_arb(fixtures / "tgt_kk.arb")
    entry = doc.strings()["greeting"]
    out = tmp_path / "out.arb"
    write_text(out, replace_values(doc, {"greeting": "Сәлем, {name}!"}))
    new = out.read_bytes()

    changed = _changed_lines(original.decode("utf-8"), new.decode("utf-8"))
    assert changed == [entry.line - 1]
    # Bytes before and after the value literal are untouched.
    prefix = doc.text[: entry.start].encode("utf-8")
    suffix = doc.text[entry.end :].encode("utf-8")
    assert new.startswith(prefix)
    assert new.endswith(suffix)
    assert parse_arb(out).strings()["greeting"].value == "Сәлем, {name}!"


def test_change_in_duplicate_hits_last_occurrence(tgt_doc):
    text = replace_values(tgt_doc, {"dupKey": "Жаңа"})
    doc = parse_arb_text(text)
    assert [e.value for e in doc.duplicates()["dupKey"]] == ["Көшірме", "Жаңа"]


def test_escaping_round_trip(tgt_doc):
    value = 'Бір "екі"\nүш \\ төрт\t\ue000'
    text = replace_values(tgt_doc, {"appTitle": value})
    doc = parse_arb_text(text)
    assert doc.strings()["appTitle"].value == value
    assert doc.strings()["appTitle"].raw == '"Бір \\"екі\\"\\nүш \\\\ төрт\\t\\ue000"'
    # Neighbouring private-use escape is kept as written.
    assert doc.strings()["currencyIcon"].raw == '"\\ue000"'
    assert [(c.value, c.line) for c in doc.comments()] == [
        (c.value, c.line) for c in tgt_doc.comments()
    ]


def test_unknown_key(tgt_doc):
    with pytest.raises(KeyError):
        replace_values(tgt_doc, {"noSuchKey": "x"})
    with pytest.raises(KeyError):
        replace_values(tgt_doc, {"@greeting": "x"})


def test_encode_json_string_keeps_cyrillic_literal():
    assert encode_json_string("Қазақ") == '"Қазақ"'


def test_lf_preserved_on_write(tmp_path):
    out = tmp_path / "a.arb"
    write_text(out, '{\n  "a": "b"\n}\n')
    assert b"\r\n" not in out.read_bytes()
