"""review.csv: one row per key with all its findings, for a native speaker to decide on.

The reviewer fills `decision` (accept / edit / reject) and, for edit, `final_text`.
accept with an empty final_text takes the suggestion as is.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from locqa.arb.writer import write_text
from locqa.errors import InputError
from locqa.models import Finding, Severity

COLUMNS = (
    "key",
    "severity",
    "issue_types",
    "source",
    "target",
    "suggestion",
    "evidence",
    "confidence",
    "decision",
    "final_text",
    "reviewer",
    "comment",
)
DECISIONS = ("accept", "edit", "reject")


@dataclass
class ReviewRow:
    key: str
    severity: Severity
    issue_types: list[str]
    source: str
    target: str
    suggestion: str | None
    evidence: list[str]
    confidence: float
    decision: str = ""
    final_text: str = ""
    reviewer: str = ""
    comment: str = ""
    line: int = 0  # line in review.csv, for error messages

    def as_csv(self) -> dict[str, str]:
        return {
            "key": self.key,
            "severity": self.severity.value,
            "issue_types": ", ".join(self.issue_types),
            "source": self.source,
            "target": self.target,
            "suggestion": self.suggestion or "",
            "evidence": " | ".join(self.evidence),
            "confidence": f"{self.confidence:.2f}",
            "decision": self.decision,
            "final_text": self.final_text,
            "reviewer": self.reviewer,
            "comment": self.comment,
        }


def build_rows(
    findings: Iterable[Finding],
    *,
    min_severity: Severity = Severity.LOW,
    min_confidence: float = 0.0,
    only: Sequence[str] = (),
    skip: Sequence[str] = (),
) -> list[ReviewRow]:
    """Group findings by key in report order (most severe first); filters apply per finding."""
    groups: dict[str, list[Finding]] = {}
    for f in findings:
        if f.severity.rank < min_severity.rank or f.confidence < min_confidence:
            continue
        if (only and f.issue_type.value not in only) or f.issue_type.value in skip:
            continue
        groups.setdefault(f.key, []).append(f)

    rows = []
    for key, fs in groups.items():
        # The suggestion of the most confident finding that has one.
        with_suggestion = sorted((f for f in fs if f.suggestion), key=lambda f: -f.confidence)
        rows.append(
            ReviewRow(
                key=key,
                severity=max((f.severity for f in fs), key=lambda s: s.rank),
                issue_types=[f.issue_type.value for f in fs],
                source=fs[0].source,
                target=fs[0].target,
                suggestion=with_suggestion[0].suggestion if with_suggestion else None,
                evidence=[f"{f.issue_type.value}: {f.evidence}" for f in fs],
                confidence=max(f.confidence for f in fs),
            )
        )
    rows.sort(key=lambda r: -r.severity.rank)  # stable: report order within a severity
    return rows


def write_review(rows: Sequence[ReviewRow], path: Path, chunk: int | None = None) -> list[Path]:
    """Write review.csv (UTF-8 with BOM, so Excel opens Cyrillic correctly). With chunk,
    rows are split into review_001.csv, review_002.csv, ... of at most chunk rows."""
    path = Path(path)
    if not chunk:
        parts = [(path, rows)]
    else:
        parts = [
            (path.with_name(f"{path.stem}_{i // chunk + 1:03d}{path.suffix}"), rows[i : i + chunk])
            for i in range(0, max(len(rows), 1), chunk)
        ]
    for part_path, part in parts:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(r.as_csv() for r in part)
        write_text(part_path, "﻿" + buf.getvalue())
    return [p for p, _ in parts]


def read_review(path: Path) -> list[ReviewRow]:
    path = Path(path)
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            missing = [
                c for c in ("key", "decision", "final_text") if c not in (reader.fieldnames or [])
            ]
            if missing:
                raise InputError(f"{path}: нет колонок {', '.join(missing)}")
            rows = []
            for line, raw in enumerate(reader, start=2):
                cell = {k: (v or "") for k, v in raw.items() if k}
                decision = cell.get("decision", "").strip().lower()
                if decision and decision not in DECISIONS:
                    raise InputError(
                        f"{path}:{line}: decision должен быть {', '.join(DECISIONS)} или пустым, "
                        f"а не '{decision}'"
                    )
                try:
                    confidence = float(cell.get("confidence") or 0)
                    severity = Severity(cell.get("severity") or "low")
                except ValueError as e:
                    raise InputError(f"{path}:{line}: {e}") from e
                rows.append(
                    ReviewRow(
                        key=cell["key"].strip(),
                        severity=severity,
                        issue_types=[
                            t.strip() for t in cell.get("issue_types", "").split(",") if t.strip()
                        ],
                        source=cell.get("source", ""),
                        target=cell.get("target", ""),
                        suggestion=cell.get("suggestion") or None,
                        evidence=[e for e in cell.get("evidence", "").split(" | ") if e],
                        confidence=confidence,
                        decision=decision,
                        final_text=cell.get("final_text", ""),
                        reviewer=cell.get("reviewer", "").strip(),
                        comment=cell.get("comment", ""),
                        line=line,
                    )
                )
            return rows
    except FileNotFoundError as e:
        raise InputError(f"файл не найден: {path}") from e
    except UnicodeDecodeError as e:
        raise InputError(f"{path}: файл не в UTF-8") from e
