from pathlib import Path

import pytest

from locqa.errors import InputError
from locqa.glossary import load_glossary
from locqa.models import Severity

REPO_GLOSSARY = Path(__file__).parent.parent / "glossary" / "glossary.csv"


def test_repo_template_loads():
    g = load_glossary(REPO_GLOSSARY)
    slang = {t.ru for t in g.terms if t.register == "slang"}
    assert {"варн", "мут", "фура", "ГК"} <= slang
    assert all(t.severity == Severity.LOW for t in g.terms if t.register == "slang")


def test_forbidden_variants_split(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text(
        "ru,kk,en,note,forbidden_kk\nсемья,отбасы,family,,жанұя | үй-іші\n", encoding="utf-8"
    )
    [term] = load_glossary(p).terms
    assert term.forbidden_kk == ("жанұя", "үй-іші")
    assert term.register == "literary"


@pytest.mark.parametrize(
    "content",
    [
        "ru,kk,en\nа,б,в\n",  # missing note column
        "ru,kk,en,note,register\nа,б,в,г,poetic\n",
        "ru,kk,en,note,severity\nа,б,в,г,critical\n",
    ],
)
def test_invalid_glossary(tmp_path, content):
    p = tmp_path / "g.csv"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(InputError):
        load_glossary(p)
