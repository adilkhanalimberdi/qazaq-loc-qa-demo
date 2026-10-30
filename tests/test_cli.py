import json

import pytest
from typer.testing import CliRunner

from locqa.cli import app
from locqa.models import ReportMeta
from locqa.report.json_writer import load_report

runner = CliRunner()


def check(fixtures, out, *extra):
    return runner.invoke(
        app,
        [
            "check",
            "--source",
            str(fixtures / "src_ru.arb"),
            "--target",
            str(fixtures / "tgt_kk.arb"),
            "--out",
            str(out),
            *extra,
        ],
    )


@pytest.mark.parametrize("command", ["check", "review-sheet", "apply", "validate", "report"])
def test_help(command):
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0


def test_check_on_fixtures(fixtures, tmp_path):
    out = tmp_path / "report.json"
    result = check(fixtures, out)
    assert result.exit_code == 1, result.output

    findings = load_report(out)  # validates the Finding schema
    got = {(f.key, f.issue_type.value) for f in findings}
    assert got == {
        ("missingInTarget", "untranslated"),
        ("emptyInTarget", "untranslated"),
        ("greeting", "placeholder_mismatch"),
        ("shopNote", "placeholder_mismatch"),
        ("okButton", "same_as_source"),
        ("profileTitle", "same_as_source"),
        ("copiedSentence", "same_as_source"),
        ("daysLeft", "plural_mismatch"),
        ("giftTo", "suffix_harmony"),
        ("saveSettings", "wrong_language"),
        ("giftReceived", "orthography"),
        ("rentButton", "length_overflow"),
    }
    # Flat array with exactly the organizer schema fields.
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    assert set(raw[0]) == {
        "key",
        "issue_type",
        "severity",
        "source",
        "target",
        "evidence",
        "suggestion",
        "confidence",
        "reviewed_by_human",
    }
    # Sorted by severity, high first.
    ranks = [f.severity.rank for f in findings]
    assert ranks == sorted(ranks, reverse=True)

    meta = ReportMeta.model_validate_json(
        (tmp_path / "report_meta.json").read_text(encoding="utf-8")
    )
    assert meta.total_findings == 12
    assert meta.target_lang == "kk"
    assert meta.counts_by_type["untranslated"] == 2
    assert any("extraKey" in w for w in meta.warnings)


def test_check_is_deterministic(fixtures, tmp_path):
    check(fixtures, tmp_path / "a.json")
    check(fixtures, tmp_path / "b.json")
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


def test_min_severity_and_only(fixtures, tmp_path):
    out = tmp_path / "r.json"
    check(fixtures, out, "--min-severity", "high")
    assert {f.severity.value for f in load_report(out)} == {"high"}

    check(fixtures, out, "--only", "untranslated")
    assert {f.issue_type.value for f in load_report(out)} == {"untranslated"}


def test_exit_0_when_clean(tmp_path):
    src = tmp_path / "intl_ru.arb"
    tgt = tmp_path / "intl_kk.arb"
    src.write_text('{"a": "Играть {n}"}', encoding="utf-8")
    tgt.write_text('{"a": "Ойнау {n}"}', encoding="utf-8")
    result = runner.invoke(
        app,
        ["check", "--source", str(src), "--target", str(tgt), "--out", str(tmp_path / "r.json")],
    )
    assert result.exit_code == 0, result.output
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8")) == []


def test_exit_2_on_bad_input(fixtures, tmp_path):
    out = tmp_path / "r.json"
    assert check(fixtures, out, "--only", "nope").exit_code == 2
    result = runner.invoke(
        app,
        [
            "check",
            "--source",
            str(fixtures / "broken.arb"),
            "--target",
            str(fixtures / "tgt_kk.arb"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 2
    assert "строка 4" in result.output
    assert (
        runner.invoke(app, ["check", "--source", "missing.arb", "--target", "x.arb"]).exit_code == 2
    )


def test_exit_3_with_llm_keeps_rule_results(fixtures, tmp_path):
    out = tmp_path / "r.json"
    result = check(fixtures, out, "--llm")
    assert result.exit_code == 3
    assert len(load_report(out)) == 12


@pytest.mark.parametrize(
    "args",
    [
        ["review-sheet", "--report", "missing.json"],
        ["apply", "--source", "s.arb", "--target", "t.arb", "--review", "r.csv"],
        ["validate", "--source", "s.arb", "--target", "t.arb"],
        ["report", "--report", "missing.json"],
    ],
)
def test_commands_report_missing_files_with_exit_2(args):
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert "файл не найден" in result.output
