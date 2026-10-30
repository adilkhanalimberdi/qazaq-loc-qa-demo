from pathlib import Path

import pytest

from locqa.arb import parse_arb
from locqa.arb.align import Pair

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def src_doc():
    return parse_arb(FIXTURES / "src_ru.arb")


@pytest.fixture
def tgt_doc():
    return parse_arb(FIXTURES / "tgt_kk.arb")


def make_pair(source: str, target: str | None, key: str = "k") -> Pair:
    return Pair(
        key=key,
        source=source,
        target=target,
        section=None,
        source_line=1,
        target_line=None if target is None else 1,
    )


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """Tests never reach a real LLM: no API key from the environment or a local .env."""
    for name in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "LOCQA_LLM_MODEL",
        "LOCQA_LLM_RPM",
        "LOCQA_LLM_BATCH",
        "LOCQA_FREE_TIER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("locqa.llm.client.load_env", lambda: None)
    monkeypatch.setattr("locqa.cli.load_env", lambda: None)
