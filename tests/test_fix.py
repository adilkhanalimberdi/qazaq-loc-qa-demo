import csv
import json

import pytest
from typer.testing import CliRunner

from locqa.arb import edit_document, parse_arb, parse_arb_text
from locqa.checks import CheckContext
from locqa.cli import app
from locqa.fix.apply import apply_review, mark_reviewed
from locqa.fix.review_sheet import ReviewRow, build_rows, read_review, write_review
from locqa.fix.validate import REVIEW_FLAG, validate
from locqa.models import Finding, IssueType, Severity
from locqa.report.html_writer import render_html

CTX = CheckContext(source_lang="ru", target_lang="kk")
runner = CliRunner()


def finding(key, issue_type, severity=Severity.HIGH, suggestion=None, confidence=0.9):
    return Finding(
        key=key,
        issue_type=issue_type,
        severity=severity,
        source="src",
        target="tgt",
        evidence="ev",
        suggestion=suggestion,
        confidence=confidence,
    )


# --- writer -----------------------------------------------------------------


def test_edit_document_flags_inserts_and_keeps_other_bytes(tgt_doc):
    flag = {REVIEW_FLAG: True}
    text = edit_document(
        tgt_doc,
        values={"menuPlay": "Ойна"},
        metadata={"menuPlay": flag, "greeting": flag, "newKey": flag},
        new_entries=[("newKey", "Жаңа", "menuPlay"), ("topKey", "Басы", None)],
    )
    doc = parse_arb_text(text)
    strings = doc.strings()
    assert strings["menuPlay"].value == "Ойна"
    assert strings["newKey"].value == "Жаңа"
    keys = list(strings)
    assert keys.index("newKey") == keys.index("menuPlay") + 1
    assert keys[0] == "topKey"  # after "@@locale"
    meta = doc.metadata()
    assert meta["menuPlay"] == flag and meta["newKey"] == flag
    # Existing metadata is merged, not replaced.
    assert meta["greeting"]["placeholders"] == {"name": {"type": "String"}}
    assert meta["greeting"][REVIEW_FLAG] is True
    # Repeated "@@comment" sections survive.
    assert [c.value for c in doc.comments()] == [c.value for c in tgt_doc.comments()]
    assert strings["dupKey"].value == "Қайталау"


# --- review sheet -----------------------------------------------------------


def test_build_rows_groups_by_key_and_filters():
    findings = [
        finding("a", IssueType.PLACEHOLDER_MISMATCH),
        finding("b", IssueType.SAME_AS_SOURCE, Severity.LOW, confidence=0.4),
        finding("a", IssueType.ORTHOGRAPHY, Severity.MEDIUM, suggestion="fix", confidence=0.95),
    ]
    rows = build_rows(findings)
    assert [r.key for r in rows] == ["a", "b"]
    assert rows[0].issue_types == ["placeholder_mismatch", "orthography"]
    assert rows[0].suggestion == "fix"
    assert [r.key for r in build_rows(findings, min_confidence=0.5)] == ["a"]
    assert [r.key for r in build_rows(findings, only=["same_as_source"])] == ["b"]


def test_review_round_trip_and_chunks(tmp_path):
    rows = build_rows([finding(k, IssueType.UNTRANSLATED) for k in "abc"])
    [path] = write_review(rows, tmp_path / "review.csv")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM for Excel
    back = read_review(path)
    assert [r.key for r in back] == ["a", "b", "c"] and back[0].line == 2
    parts = write_review(rows, tmp_path / "r.csv", chunk=2)
    assert [p.name for p in parts] == ["r_001.csv", "r_002.csv"]


def test_review_rejects_unknown_decision(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("key,decision,final_text\nk,maybe,\n", encoding="utf-8")
    with pytest.raises(Exception, match="decision"):
        read_review(p)


# --- apply ------------------------------------------------------------------


def row(key, decision, final_text="", suggestion=None):
    return ReviewRow(
        key=key,
        severity=Severity.HIGH,
        issue_types=["x"],
        source="",
        target="",
        suggestion=suggestion,
        evidence=[],
        confidence=1.0,
        decision=decision,
        final_text=final_text,
        reviewer="n",
        line=2,
    )


def test_apply_only_decided_rows_and_refuses_broken_placeholders(src_doc, tgt_doc):
    rows = [
        row("greeting", "edit", "Сәлем, {name}!"),
        row("menuPlay", "accept", suggestion="Ойна"),
        row("profileLevel", "edit", "Деңгей {level}"),  # drops {max}
        row("menuSettings", "reject", "x"),
        row("shopBuy", ""),
        row("missingInTarget", "edit", "Аударылмаған жол"),
        row("coinsCount", "edit", ""),  # edit without text
    ]
    result = apply_review(tgt_doc, src_doc, rows, CTX, reviewed_at="t")
    assert [c.key for c in result.changes] == ["greeting", "menuPlay", "missingInTarget"]
    assert len(result.refused) == 2 and "{max}" in result.refused[0]
    assert result.skipped == 2
    fixed = parse_arb_text(result.text)
    assert fixed.strings()["greeting"].value == "Сәлем, {name}!"
    assert fixed.strings()["menuSettings"].value == "Баптаулар"
    assert fixed.metadata()["missingInTarget"][REVIEW_FLAG] is True
    check = validate(src_doc, fixed, CTX, original=tgt_doc)
    assert check.ok, check.errors
    assert check.changed == 3


def test_validate_catches_unflagged_change_and_lost_key(src_doc, tgt_doc):
    text = edit_document(tgt_doc, values={"menuPlay": "Ойна"})
    text = text.replace('  "okButton": "ОК",\n', "")
    check = validate(src_doc, parse_arb_text(text), CTX, original=tgt_doc)
    assert any("без флага" in e and "menuPlay" in e for e in check.errors)
    assert any("потеряны ключи: okButton" in e for e in check.errors)


def test_mark_reviewed():
    findings = [finding("a", IssueType.UNTRANSLATED), finding("b", IssueType.UNTRANSLATED)]
    from locqa.fix.apply import AppliedChange

    change = AppliedChange("a", None, "жаңа", "edit", "n", "", ["untranslated"])
    marked = mark_reviewed(findings, [change])
    assert marked[0].reviewed_by_human and marked[0].suggestion == "жаңа"
    assert not marked[1].reviewed_by_human


# --- html -------------------------------------------------------------------


def test_html_is_self_contained_and_escapes_script_end():
    f = finding("k", IssueType.UNTRANSLATED).model_copy(update={"target": "</script><b>x"})
    page = render_html([f])
    assert "<\\/script><b>x" in page
    assert "http" not in page.split("<body>")[0]  # no external resources in <head>


# --- CLI end to end ---------------------------------------------------------


def test_cli_full_cycle(fixtures, tmp_path):
    src, tgt = fixtures / "src_ru.arb", fixtures / "tgt_kk.arb"
    report, review = tmp_path / "report.json", tmp_path / "review.csv"
    html = tmp_path / "report.html"
    args = ["check", "--source", str(src), "--target", str(tgt), "--out", str(report)]
    assert runner.invoke(app, [*args, "--html", str(html)]).exit_code == 1
    assert html.exists()
    assert (
        runner.invoke(
            app, ["review-sheet", "--report", str(report), "--out", str(review)]
        ).exit_code
        == 0
    )

    rows = list(csv.DictReader(review.open(encoding="utf-8-sig")))
    for r in rows:
        if r["key"] == "greeting":
            r["decision"], r["final_text"] = "edit", "Сәлем, {name}!"
    with review.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    fixed, log = tmp_path / "fixed.arb", tmp_path / "log.json"
    res = runner.invoke(
        app,
        [
            "apply",
            "--source",
            str(src),
            "--target",
            str(tgt),
            "--review",
            str(review),
            "--out",
            str(fixed),
            "--log",
            str(log),
            "--report",
            str(report),
        ],
    )
    assert res.exit_code == 0, res.output
    assert json.loads(log.read_text(encoding="utf-8"))[0]["key"] == "greeting"
    reviewed = [f for f in json.loads(report.read_text(encoding="utf-8")) if f["reviewed_by_human"]]
    assert [f["key"] for f in reviewed] == ["greeting"]

    res = runner.invoke(
        app,
        [
            "validate",
            "--source",
            str(src),
            "--target",
            str(fixed),
            "--original",
            str(tgt),
            "--no-flutter",
        ],
    )
    assert res.exit_code == 0, res.output
    assert (
        runner.invoke(app, ["report", "--report", str(report), "--html", str(html)]).exit_code == 0
    )
    assert parse_arb(fixed).strings()["greeting"].value == "Сәлем, {name}!"
