"""report.json (flat array of Finding) and report_meta.json."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from locqa.arb.writer import write_text
from locqa.errors import InputError
from locqa.models import Finding, ReportMeta

_findings_adapter = TypeAdapter(list[Finding])


def write_report(findings: Sequence[Finding], path: Path) -> None:
    data = [f.model_dump(mode="json") for f in findings]
    write_text(Path(path), json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def write_meta(meta: ReportMeta, path: Path) -> None:
    write_text(
        Path(path), json.dumps(meta.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    )


def meta_path_for(report_path: Path) -> Path:
    report_path = Path(report_path)
    return report_path.with_name(f"{report_path.stem}_meta.json")


def load_report(path: Path) -> list[Finding]:
    path = Path(path)
    try:
        return _findings_adapter.validate_json(path.read_bytes())
    except FileNotFoundError as e:
        raise InputError(f"файл не найден: {path}") from e
    except ValidationError as e:
        raise InputError(f"{path}: не соответствует схеме Finding: {e}") from e


def load_meta(path: Path) -> ReportMeta | None:
    """report_meta.json, or None if it is absent or from another version of the schema."""
    try:
        return ReportMeta.model_validate_json(Path(path).read_bytes())
    except (FileNotFoundError, ValidationError):
        return None
