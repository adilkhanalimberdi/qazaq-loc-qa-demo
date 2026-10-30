import json

import pytest
from typer.testing import CliRunner

from conftest import make_pair
from locqa.checks import CheckContext
from locqa.cli import app
from locqa.errors import LLMError
from locqa.llm.client import FakeClient, GeminiClient
from locqa.llm.cost import CostTracker
from locqa.llm.layer import LLMOptions, run_llm, select_items, suspicion
from locqa.models import Finding, IssueType, Severity

CTX = CheckContext(source_lang="ru", target_lang="kk")


def finding(key, issue_type, source, target, severity=Severity.HIGH, suggestion=None):
    return Finding(
        key=key,
        issue_type=issue_type,
        severity=severity,
        source=source,
        target=target,
        evidence="ev",
        suggestion=suggestion,
        confidence=0.9,
    )


def responder(answers_by_key):
    """Answer each item of a batch by its key."""

    def respond(system, user):
        items = json.loads(user)["items"]
        out = [
            {"id": it["id"], **answers_by_key[it["key"]]}
            for it in items
            if it["key"] in answers_by_key
        ]
        return json.dumps({"items": out}, ensure_ascii=False)

    return respond


PAIRS = [
    make_pair("Привет, {name}!", "Сәлем, {nam}!", key="greet"),
    make_pair("Профиль", "Профиль", key="prof"),
    make_pair("Купить машину", "Купить көлік", key="buy"),
    make_pair("Играть", "Ойнау", key="play"),
]
FINDINGS = [
    finding("greet", IssueType.PLACEHOLDER_MISMATCH, "Привет, {name}!", "Сәлем, {nam}!"),
    finding("prof", IssueType.SAME_AS_SOURCE, "Профиль", "Профиль", Severity.MEDIUM),
]


def test_suspicion_signals():
    assert suspicion(make_pair("Купить машину", "Купить көлік"), CTX)  # Russian verb
    assert suspicion(make_pair("x", "Бұл и сол"), CTX)  # Russian conjunction
    assert suspicion(make_pair("Играть", "Ойнау"), CTX) == []


def test_select_items_fix_first_then_suspects():
    items = select_items(PAIRS, FINDINGS, CTX, LLMOptions(model="fake"))
    assert [(i.key, i.task) for i in items] == [
        ("greet", "fix"),
        ("prof", "fix"),
        ("buy", "review"),
    ]
    assert items[0].found and items[0].id == 1
    everything = select_items(PAIRS, FINDINGS, CTX, LLMOptions(model="fake", scope="all"))
    assert "play" in [i.key for i in everything]
    assert len(select_items(PAIRS, FINDINGS, CTX, LLMOptions(model="fake", max_strings=1))) == 1


def test_run_llm_merges_validates_and_dismisses():
    client = FakeClient(
        responder(
            {
                "greet": {"verdict": "issue", "agree": True, "suggestion": "Сәлем, {name}!"},
                "prof": {"verdict": "ok", "agree": False, "confidence": 0.9},
                "buy": {
                    "verdict": "issue",
                    "issue_type": "machine_translation_suspect",
                    "severity": "medium",
                    "confidence": 0.85,
                    "evidence": "«Купить» не переведено",
                    "suggestion": "Көлік сатып алу",
                },
            }
        )
    )
    result = run_llm(PAIRS, FINDINGS, CTX, client, LLMOptions(model="fake"))
    by_key = {f.key: f for f in result.findings}
    assert by_key["greet"].suggestion == "Сәлем, {name}!"
    assert "prof" not in by_key  # dismissed as a legitimate loanword
    mts = by_key["buy"]
    assert mts.issue_type == IssueType.MACHINE_TRANSLATION_SUSPECT
    assert mts.evidence.startswith("LLM:") and mts.suggestion == "Көлік сатып алу"
    assert result.meta["suggestions_added"] == 1 and result.meta["dismissed"] == 1
    assert result.meta["requests"] == 1 and result.error is None


def test_run_llm_rejects_suggestion_that_breaks_placeholders_and_lowers_weak_findings():
    client = FakeClient(
        responder(
            {
                "greet": {"verdict": "issue", "agree": True, "suggestion": "Сәлем!"},
                "buy": {
                    "verdict": "issue",
                    "issue_type": "machine_translation_suspect",
                    "confidence": 0.3,
                    "evidence": "сомнительно",
                },
            }
        )
    )
    result = run_llm(PAIRS, FINDINGS, CTX, client, LLMOptions(model="fake"))
    by_key = {f.key: f for f in result.findings}
    assert by_key["greet"].suggestion is None
    assert result.meta["suggestions_rejected"] == 1
    assert by_key["buy"].severity == Severity.LOW


def test_cache_avoids_second_request(tmp_path):
    client = FakeClient(responder({}))
    options = LLMOptions(model="fake", cache_dir=tmp_path)
    run_llm(PAIRS, FINDINGS, CTX, client, options)
    second = run_llm(PAIRS, FINDINGS, CTX, client, options)
    assert len(client.calls) == 1
    assert second.meta["cached_requests"] == 1 and second.meta["requests"] == 0


def test_bad_json_is_retried_once():
    replies = iter(["not json", json.dumps({"items": []})])
    client = FakeClient(lambda s, u: next(replies))
    result = run_llm(PAIRS, FINDINGS, CTX, client, LLMOptions(model="fake"))
    assert len(client.calls) == 2 and result.meta["bad_responses"] == 1


def test_budget_stops_between_batches(monkeypatch):
    monkeypatch.setenv("LOCQA_PRICE_INPUT", "1000000")  # $1 per token
    monkeypatch.setenv("LOCQA_PRICE_OUTPUT", "0")
    client = FakeClient(responder({}))
    options = LLMOptions(model="fake", budget_usd=1.0, batch_size=1)
    result = run_llm(PAIRS, FINDINGS, CTX, client, options)
    assert len(client.calls) == 1
    assert "бюджет" in result.error


def test_network_error_keeps_partial_results():
    def broken(system, user):
        raise LLMError("сеть недоступна")

    result = run_llm(PAIRS, FINDINGS, CTX, FakeClient(broken), LLMOptions(model="fake"))
    assert result.error == "сеть недоступна"
    assert {f.key for f in result.findings} == {"greet", "prof"}


def test_cost_tracker():
    t = CostTracker(model="gemini-2.5-flash")
    t.add(1_000_000, 100_000)
    assert t.cost_usd == pytest.approx(0.30 + 0.25)
    assert t.as_dict()["price_usd_per_1m"] == [0.30, 2.50]


def test_gemini_without_key_is_an_llm_error():
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        GeminiClient("gemini-2.5-flash")


def test_cli_llm_with_fake_client(fixtures, tmp_path, monkeypatch):
    def fake_make_client(model):
        return FakeClient(
            responder(
                {"greeting": {"verdict": "issue", "agree": True, "suggestion": "Сәлем, {name}!"}}
            ),
            model=model,
        )

    monkeypatch.setattr("locqa.cli.make_client", fake_make_client)
    out = tmp_path / "report.json"
    result = CliRunner().invoke(
        app,
        [
            "check",
            "--source",
            str(fixtures / "src_ru.arb"),
            "--target",
            str(fixtures / "tgt_kk.arb"),
            "--out",
            str(out),
            "--llm",
            "--llm-model",
            "fake",
        ],
    )
    assert result.exit_code == 1, result.output
    greeting = [f for f in json.loads(out.read_text(encoding="utf-8")) if f["key"] == "greeting"]
    assert greeting[0]["suggestion"] == "Сәлем, {name}!"
    cost = json.loads((tmp_path / "cost.json").read_text(encoding="utf-8"))
    assert cost["model"] == "fake" and cost["requests"] >= 1
    meta = json.loads((tmp_path / "report_meta.json").read_text(encoding="utf-8"))
    assert meta["llm"]["prompt_version"] == meta["prompt_version"]
