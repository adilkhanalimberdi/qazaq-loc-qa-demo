"""The `check` pipeline: parse, align, run checks, merge and sort findings."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from locqa import __version__
from locqa.arb.align import Pair, align
from locqa.arb.parser import ArbDocument, parse_arb
from locqa.checks import CheckContext, get_checks
from locqa.config import Config
from locqa.glossary import load_glossary
from locqa.llm.client import LLMClient
from locqa.llm.layer import LLMOptions, run_llm
from locqa.models import Finding, IssueType, ReportMeta, Severity

_LANG_FROM_NAME = re.compile(r"_([A-Za-z]{2,3}(?:[_-][A-Za-z]{2,4})?)\.arb$")


@dataclass
class CheckResult:
    findings: list[Finding]
    meta: ReportMeta
    warnings: list[str] = field(default_factory=list)
    pairs: list[Pair] = field(default_factory=list)
    ctx: CheckContext | None = None


def detect_lang(doc: ArbDocument, fallback: str) -> str:
    """@@locale, then the intl_xx.arb file name convention, then fallback."""
    locale = doc.locale()
    if locale:
        return locale
    if doc.path:
        m = _LANG_FROM_NAME.search(doc.path.name)
        if m:
            return m.group(1)
    return fallback


def sort_and_dedupe(findings: Iterable[Finding], key_order: dict[str, int]) -> list[Finding]:
    """Stable order: severity (high first), key position in source, issue type.
    One finding per (key, issue_type): the most severe one is kept."""
    type_order = {t: i for i, t in enumerate(IssueType)}
    ordered = sorted(
        findings,
        key=lambda f: (
            -f.severity.rank,
            key_order.get(f.key, len(key_order)),
            type_order[f.issue_type],
            f.key,
        ),
    )
    seen: set[tuple[str, IssueType]] = set()
    result = []
    for f in ordered:
        if (f.key, f.issue_type) in seen:
            continue
        seen.add((f.key, f.issue_type))
        result.append(f)
    return result


def _sha256(doc: ArbDocument) -> str:
    return hashlib.sha256(doc.text.encode("utf-8")).hexdigest()


def run_check(
    source_path: Path,
    target_path: Path,
    *,
    glossary_path: Path | None = None,
    context_paths: Sequence[Path] = (),
    only: Iterable[str] | None = None,
    skip: Iterable[str] = (),
    min_severity: Severity = Severity.LOW,
    lang: str | None = None,
    config: Config | None = None,
) -> CheckResult:
    checks = get_checks(only, skip)  # fail fast on unknown names before reading files
    source = parse_arb(source_path)
    target = parse_arb(target_path)
    context = {}
    for p in context_paths:
        doc = parse_arb(p)
        context[detect_lang(doc, fallback=Path(p).stem)] = doc
    glossary = load_glossary(glossary_path) if glossary_path else None

    pairs, warnings = align(source, target, context)
    ctx = CheckContext(
        source_lang=detect_lang(source, fallback="ru"),
        target_lang=lang or detect_lang(target, fallback="kk"),
        config=config or Config(),
        glossary=glossary,
    )

    raw: list[Finding] = []
    for check in checks:
        raw.extend(check.run(pairs, ctx))
    key_order = {p.key: i for i, p in enumerate(pairs)}
    findings = [f for f in sort_and_dedupe(raw, key_order) if f.severity.rank >= min_severity.rank]

    meta = ReportMeta(
        tool_version=__version__,
        prompt_version=None,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        source_file=str(source_path),
        target_file=str(target_path),
        source_sha256=_sha256(source),
        target_sha256=_sha256(target),
        source_lang=ctx.source_lang,
        target_lang=ctx.target_lang,
        min_severity=min_severity,
        checks_run=[c.name for c in checks],
        total_findings=len(findings),
        counts_by_type=dict(Counter(f.issue_type.value for f in findings)),
        counts_by_severity=dict(Counter(f.severity.value for f in findings)),
        warnings=warnings,
        llm=None,
    )
    return CheckResult(findings=findings, meta=meta, warnings=warnings, pairs=pairs, ctx=ctx)


def run_llm_stage(result: CheckResult, client: LLMClient, options: LLMOptions) -> str | None:
    """Add LLM suggestions and findings to a rule-based result in place.
    Returns why the stage stopped early, or None."""
    assert result.ctx is not None
    stage = run_llm(result.pairs, result.findings, result.ctx, client, options)
    key_order = {p.key: i for i, p in enumerate(result.pairs)}
    min_rank = result.meta.min_severity.rank
    findings = [
        f for f in sort_and_dedupe(stage.findings, key_order) if f.severity.rank >= min_rank
    ]
    result.findings = findings
    result.meta = result.meta.model_copy(
        update={
            "prompt_version": stage.meta["prompt_version"],
            "total_findings": len(findings),
            "counts_by_type": dict(Counter(f.issue_type.value for f in findings)),
            "counts_by_severity": dict(Counter(f.severity.value for f in findings)),
            "llm": stage.meta,
        }
    )
    return stage.error
