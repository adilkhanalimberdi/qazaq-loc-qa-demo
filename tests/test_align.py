from locqa.arb import align, parse_arb_text


def test_pairs_follow_source_order(src_doc, tgt_doc):
    pairs, _ = align(src_doc, tgt_doc)
    assert [p.key for p in pairs] == list(src_doc.strings())
    by_key = {p.key: p for p in pairs}
    assert by_key["missingInTarget"].target is None
    assert by_key["missingInTarget"].target_line is None
    assert by_key["menuPlay"].section == "MENU"


def test_warnings_for_extra_and_duplicate_keys(src_doc, tgt_doc):
    _, warnings = align(src_doc, tgt_doc)
    text = "\n".join(warnings)
    assert "extraKey" in text
    assert "dupKey" in text  # conflicting duplicate in target
    src_warning = next(w for w in warnings if "src_ru.arb" in w)
    assert "разными значениями" not in src_warning  # source duplicate has equal values


def test_context_documents():
    src = parse_arb_text('{"a": "один", "b": "два"}')
    tgt = parse_arb_text('{"a": "бір", "b": "екі"}')
    en = parse_arb_text('{"a": "one"}')
    pairs, warnings = align(src, tgt, {"en": en})
    assert pairs[0].context == {"en": "one"}
    assert pairs[1].context == {}
    assert warnings == []
