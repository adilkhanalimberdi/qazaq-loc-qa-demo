"""Shared data contract: Finding (one item of report.json) and ReportMeta."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        """Higher means more severe."""
        return {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2}[self]


class IssueType(StrEnum):
    UNTRANSLATED = "untranslated"
    SAME_AS_SOURCE = "same_as_source"
    PLACEHOLDER_MISMATCH = "placeholder_mismatch"
    PLURAL_MISMATCH = "plural_mismatch"
    GLOSSARY_VIOLATION = "glossary_violation"
    LENGTH_OVERFLOW = "length_overflow"
    MACHINE_TRANSLATION_SUSPECT = "machine_translation_suspect"
    INCONSISTENT_TERM = "inconsistent_term"
    SUFFIX_HARMONY = "suffix_harmony"
    ORTHOGRAPHY = "orthography"
    WRONG_LANGUAGE = "wrong_language"


class Finding(BaseModel):
    """One issue. Field set matches the organizers' report.json schema exactly."""

    model_config = ConfigDict(extra="forbid")

    key: str
    issue_type: IssueType
    severity: Severity
    source: str
    target: str
    evidence: str
    suggestion: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reviewed_by_human: bool = False


class ReportMeta(BaseModel):
    """Run summary written to report_meta.json next to report.json."""

    model_config = ConfigDict(extra="forbid")

    tool_version: str
    prompt_version: str | None = None
    generated_at: str
    source_file: str
    target_file: str
    source_sha256: str
    target_sha256: str
    source_lang: str
    target_lang: str
    min_severity: Severity
    checks_run: list[str]
    total_findings: int
    counts_by_type: dict[str, int]
    counts_by_severity: dict[str, int]
    warnings: list[str]
    llm: dict | None = None
