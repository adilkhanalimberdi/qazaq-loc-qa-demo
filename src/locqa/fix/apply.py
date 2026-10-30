"""Apply a native speaker's decisions from review.csv to the target ARB.

Only rows with decision accept or edit change the file; every changed string gets the
human-review flag in its "@key" metadata. Rows whose new text breaks placeholders or ICU
are refused, so the fixed file keeps compiling.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from locqa.arb.parser import ArbDocument
from locqa.arb.writer import edit_document
from locqa.checks.base import CheckContext
from locqa.fix.review_sheet import ReviewRow
from locqa.fix.validate import REVIEW_FLAG, text_problems
from locqa.models import Finding


@dataclass
class AppliedChange:
    key: str
    old: str | None  # None: the key was missing and has been added
    new: str
    decision: str
    reviewer: str
    comment: str
    issue_types: list[str]

    def as_log(self) -> dict:
        return {
            "key": self.key,
            "old": self.old,
            "new": self.new,
            "decision": self.decision,
            "reviewer": self.reviewer,
            "comment": self.comment,
            "issue_types": self.issue_types,
            "reviewed_by_human": True,
        }


@dataclass
class ApplyResult:
    text: str
    changes: list[AppliedChange] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)  # "key: reason"
    skipped: int = 0  # rows without accept/edit


def _new_text(row: ReviewRow) -> str | None:
    if row.decision == "edit":
        return row.final_text if row.final_text.strip() else None
    if row.decision == "accept":
        return row.final_text if row.final_text.strip() else row.suggestion
    return None


def apply_review(
    target: ArbDocument,
    source: ArbDocument,
    rows: Sequence[ReviewRow],
    ctx: CheckContext,
    reviewed_at: str | None = None,
) -> ApplyResult:
    src = source.strings()
    tgt = target.strings()
    source_order = list(src)
    reviewed_at = reviewed_at or datetime.now(UTC).isoformat(timespec="seconds")

    values: dict[str, str] = {}
    metadata: dict[str, dict] = {}
    new_entries: list[tuple[str, str, str | None]] = []
    result = ApplyResult(text=target.text)

    for row in rows:
        if row.decision not in ("accept", "edit"):
            result.skipped += 1
            continue
        where = f"{row.key} (строка {row.line} review.csv)"
        if row.key not in src:
            result.refused.append(f"{where}: ключа нет в исходном файле")
            continue
        new = _new_text(row)
        if new is None:
            need = "final_text" if row.decision == "edit" else "suggestion или final_text"
            result.refused.append(f"{where}: decision={row.decision}, но {need} пустой")
            continue
        problems = text_problems(row.key, src[row.key].value, new, ctx)
        if problems:
            result.refused.append(f"{where}: {'; '.join(problems)}")
            continue
        old = tgt[row.key].value if row.key in tgt else None
        if old == new:
            result.skipped += 1
            continue
        flag = {REVIEW_FLAG: True, "x-reviewed_at": reviewed_at}
        if row.reviewer:
            flag["x-reviewer"] = row.reviewer
        metadata[row.key] = flag
        if old is None:
            # Keep source order: after the closest preceding source key present in the target.
            idx = source_order.index(row.key)
            anchor = next((k for k in reversed(source_order[:idx]) if k in tgt), None)
            new_entries.append((row.key, new, anchor))
        else:
            values[row.key] = new
        result.changes.append(
            AppliedChange(
                key=row.key,
                old=old,
                new=new,
                decision=row.decision,
                reviewer=row.reviewer,
                comment=row.comment,
                issue_types=row.issue_types,
            )
        )

    result.text = edit_document(target, values, metadata, new_entries)
    return result


def mark_reviewed(findings: Sequence[Finding], changes: Sequence[AppliedChange]) -> list[Finding]:
    """report.json findings with reviewed_by_human set for the keys a person has decided on,
    and the suggestion replaced by the text that went into the file."""
    applied = {c.key: c.new for c in changes}
    return [
        f.model_copy(update={"reviewed_by_human": True, "suggestion": applied[f.key]})
        if f.key in applied
        else f
        for f in findings
    ]
