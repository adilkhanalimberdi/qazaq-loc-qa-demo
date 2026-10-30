"""Self-contained HTML report: summary, filters and the findings table. No external files,
so it can be attached to a CI run or sent as is."""

from __future__ import annotations

import html
import json
from collections.abc import Sequence
from functools import cache
from importlib.resources import files
from pathlib import Path

from locqa.arb.writer import write_text
from locqa.models import Finding, ReportMeta


def _json_for_script(value: object) -> str:
    # "</" would end the <script> element early; " " breaks older JS parsers.
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


@cache
def _template() -> str:
    return files("locqa.report").joinpath("templates/report.html").read_text(encoding="utf-8")


def render_html(findings: Sequence[Finding], meta: ReportMeta | None = None) -> str:
    data = [f.model_dump(mode="json") for f in findings]
    meta_data = meta.model_dump(mode="json") if meta else None
    title = "Отчёт locqa"
    if meta:
        title += f": {Path(meta.target_file).name}"
    return (
        _template()
        .replace("{{TITLE}}", html.escape(title))
        .replace("{{DATA}}", _json_for_script({"findings": data, "meta": meta_data}))
    )


def write_html(findings: Sequence[Finding], path: Path, meta: ReportMeta | None = None) -> None:
    write_text(Path(path), render_html(findings, meta))
