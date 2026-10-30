"""The LLM stage: suggestions for rule findings and a review for machine translation.

Only selected strings go to the model, in batches, with a cache and a budget. Every
suggestion is checked by code (placeholders, tags, ICU) before it reaches the report, and the
model never writes to the ARB file.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from locqa import langs
from locqa.arb.align import Pair
from locqa.checks.base import CheckContext
from locqa.errors import LLMError
from locqa.fix.validate import text_problems
from locqa.llm.cache import ResponseCache
from locqa.llm.client import LLMClient
from locqa.llm.cost import CostTracker
from locqa.llm.prompts import (
    LLM_ISSUE_TYPES,
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    PromptItem,
    system_prompt,
    user_prompt,
)
from locqa.models import Finding, IssueType, Severity
from locqa.text import WORD_RE, mask_markup

# Rule findings the model may overrule when it is confident they are false alarms.
DISMISSABLE = frozenset({IssueType.SAME_AS_SOURCE, IssueType.INCONSISTENT_TERM})
_DISMISS_CONFIDENCE = 0.8

# Russian function words that never occur as words in Kazakh text.
_RU_FUNCTION_WORDS = frozenset(
    {
        "и", "в", "для", "что", "по", "от", "за", "из", "или", "это", "как",
        "вы", "ваш", "ваши", "все", "уже", "если", "при", "чтобы", "будет", "можно", "нет",
    }
)  # fmt: skip


# Verb, adjective and noun endings that Kazakh words do not have (unlike -ны, -ты, -лы).
_RU_ONLY_ENDING = re.compile(
    r"(?:ться|тся|ешь|ете|ть|ый|ий|ая|яя|ое|ые|ого|ому|ыми|ими|ение|ость|ами|ями)$"
)


@dataclass
class LLMOptions:
    model: str
    scope: str = "suspects"  # "suspects": rule findings and heuristic suspects; "all"
    max_strings: int | None = None
    budget_usd: float | None = None
    batch_size: int = 20
    cache_dir: Path | None = None
    min_confidence: float = 0.6
    fix_min_severity: Severity = Severity.MEDIUM


@dataclass
class LLMStageResult:
    findings: list[Finding]
    meta: dict
    error: str | None = None  # why the stage stopped early (budget, network); results are kept
    items: int = 0
    stats: dict[str, int] = field(default_factory=dict)


def suspicion(p: Pair, ctx: CheckContext) -> list[str]:
    """Cheap signals that a translation may be machine-made or contain source-language text."""
    if not p.target:
        return []
    reasons = []
    words = [w.lower() for w in WORD_RE.findall(mask_markup(p.target))]
    target_profile = langs.profile(ctx.target_lang)
    markers = target_profile.markers if target_profile else None
    if ctx.source_lang.startswith("ru") and markers:
        russian = [
            w for w in words if len(w) >= 4 and _RU_ONLY_ENDING.search(w) and not markers.search(w)
        ]
        if russian:
            reasons.append("слова с русскими окончаниями: " + ", ".join(russian[:3]))
    if ctx.source_lang.startswith("ru"):
        function_words = [w for w in words if w in _RU_FUNCTION_WORDS]
        if function_words:
            reasons.append("служебные слова языка исходника: " + ", ".join(function_words[:3]))
    if markers and len(words) >= 5 and not markers.search(p.target):
        reasons.append("длинная строка без специфичных букв языка перевода")
    src_len, tgt_len = len(p.source.strip()), len(p.target.strip())
    if src_len >= 30 and tgt_len < src_len * 0.4:
        reasons.append(f"перевод подозрительно короткий: {tgt_len} символов против {src_len}")
    return reasons


def _glossary_hints(p: Pair, ctx: CheckContext) -> list[str]:
    if ctx.glossary is None:
        return []
    hints = []
    for term in ctx.glossary.terms:
        if term.kk_variants and term.find_in_source(p.source):
            hint = f"{term.ru} → {' / '.join(term.kk_variants)}"
            if term.register == "slang":
                hint += " (сленг игроков)"
            hints.append(hint)
    return hints


def _neighbours(pairs: Sequence[Pair], index: int) -> list[str]:
    p = pairs[index]
    out = []
    for j in (index - 1, index + 1):
        if 0 <= j < len(pairs) and pairs[j].section == p.section and pairs[j].target:
            out.append(f"{pairs[j].key}: {pairs[j].source} → {pairs[j].target}")
    return out


def select_items(
    pairs: Sequence[Pair], findings: Sequence[Finding], ctx: CheckContext, options: LLMOptions
) -> list[PromptItem]:
    by_key: dict[str, list[Finding]] = {}
    for f in findings:
        by_key.setdefault(f.key, []).append(f)

    fix: list[tuple[int, int, PromptItem]] = []
    review: list[tuple[int, int, PromptItem]] = []
    for i, p in enumerate(pairs):
        if not p.source.strip():
            continue
        fs = by_key.get(p.key, [])
        needs_fix = [
            f
            for f in fs
            if f.severity.rank >= options.fix_min_severity.rank
            and (f.suggestion is None or f.issue_type in DISMISSABLE)
        ]
        item = PromptItem(
            id=0,
            key=p.key,
            task="fix" if needs_fix else "review",
            source=p.source,
            target=p.target or "",
            section=p.section,
            context=dict(p.context),
            glossary=_glossary_hints(p, ctx),
            neighbours=_neighbours(pairs, i),
        )
        if needs_fix:
            item.found = [f"{f.issue_type.value}: {f.evidence}" for f in needs_fix]
            rank = max(f.severity.rank for f in needs_fix)
            fix.append((-rank, i, item))
            continue
        if fs or not p.target or p.target.strip() == p.source.strip():
            continue  # already reported, or nothing to review
        reasons = suspicion(p, ctx)
        if options.scope == "all" or reasons:
            item.found = [f"подозрение: {r}" for r in reasons]
            review.append((-len(reasons), i, item))

    items = [it for _, _, it in sorted(fix)] + [it for _, _, it in sorted(review)]
    if options.max_strings is not None:
        items = items[: options.max_strings]
    for n, it in enumerate(items, start=1):
        it.id = n
    return items


def _parse(text: str) -> dict[int, dict]:
    data = json.loads(text)
    return {int(x["id"]): x for x in data.get("items", []) if "id" in x}


def run_llm(
    pairs: Sequence[Pair],
    findings: Sequence[Finding],
    ctx: CheckContext,
    client: LLMClient,
    options: LLMOptions,
) -> LLMStageResult:
    items = select_items(pairs, findings, ctx, options)
    tracker = CostTracker(model=client.model, budget_usd=options.budget_usd)
    cache = ResponseCache(options.cache_dir)
    system = system_prompt(ctx.source_lang, ctx.target_lang)
    answers: dict[int, dict] = {}
    error = None
    stats = {"batches": 0, "bad_responses": 0}

    for start in range(0, len(items), options.batch_size):
        if tracker.over_budget:
            error = f"достигнут бюджет ${options.budget_usd}: обработано {start} из {len(items)}"
            break
        batch = items[start : start + options.batch_size]
        user = user_prompt(batch)
        key = cache.key(client.model, PROMPT_VERSION, system, user)
        text = cache.get(key)
        if text is not None:
            tracker.cached_requests += 1
        try:
            for attempt in range(2):
                if text is None:
                    response = client.complete(system, user, RESPONSE_SCHEMA)
                    tracker.add(response.input_tokens, response.output_tokens)
                    text = response.text
                try:
                    parsed = _parse(text)
                except (ValueError, TypeError, KeyError):
                    stats["bad_responses"] += 1
                    text = None  # retry once with a fresh request
                    if attempt == 1:
                        parsed = {}
                    continue
                cache.put(key, text)
                break
        except LLMError as e:
            error = str(e)
            break
        stats["batches"] += 1
        answers.update(parsed)

    result_findings, merge_stats = _merge(items, answers, findings, ctx, options)
    stats.update(merge_stats)
    meta = {
        **tracker.as_dict(),
        "prompt_version": PROMPT_VERSION,
        "scope": options.scope,
        "strings_selected": len(items),
        "strings_answered": len(answers),
        **stats,
        "stopped": error,
    }
    return LLMStageResult(result_findings, meta, error, len(items), stats)


def _merge(
    items: Sequence[PromptItem],
    answers: dict[int, dict],
    findings: Sequence[Finding],
    ctx: CheckContext,
    options: LLMOptions,
) -> tuple[list[Finding], dict[str, int]]:
    stats = {"suggestions_added": 0, "suggestions_rejected": 0, "dismissed": 0, "new_findings": 0}
    by_id = {it.id: it for it in items}
    suggestions: dict[str, str] = {}
    dismissed: set[str] = set()
    new: list[Finding] = []
    existing = {(f.key, f.issue_type) for f in findings}

    for item_id, answer in answers.items():
        item = by_id.get(item_id)
        if item is None:
            continue
        suggestion = answer.get("suggestion")
        if isinstance(suggestion, str) and suggestion.strip():
            problems = text_problems(item.key, item.source, suggestion, ctx)
            if problems or suggestion.strip() == item.target.strip():
                stats["suggestions_rejected"] += 1
                suggestion = None
        else:
            suggestion = None
        confidence = _clamp(answer.get("confidence", 0.0))

        if item.task == "fix":
            if answer.get("agree") is False and confidence >= _DISMISS_CONFIDENCE:
                dismissed.add(item.key)
            elif suggestion:
                suggestions[item.key] = suggestion
            continue

        issue_type = answer.get("issue_type")
        if answer.get("verdict") != "issue" or issue_type not in LLM_ISSUE_TYPES:
            continue
        issue = IssueType(issue_type)
        if (item.key, issue) in existing:
            continue
        try:
            severity = Severity(answer.get("severity", "medium"))
        except ValueError:
            severity = Severity.MEDIUM
        if confidence < options.min_confidence:
            severity = Severity.LOW  # kept for the record, filtered out of the review sheet
        evidence = (
            str(answer.get("evidence") or "").strip() or "модель считает перевод неестественным"
        )
        new.append(
            Finding(
                key=item.key,
                issue_type=issue,
                severity=severity,
                source=item.source,
                target=item.target,
                evidence=f"LLM: {evidence}",
                suggestion=suggestion,
                confidence=round(confidence, 2),
            )
        )

    merged = []
    for f in findings:
        if f.key in dismissed and f.issue_type in DISMISSABLE:
            stats["dismissed"] += 1
            continue
        if f.suggestion is None and f.key in suggestions:
            f = f.model_copy(update={"suggestion": suggestions[f.key]})
            stats["suggestions_added"] += 1
        merged.append(f)
    stats["new_findings"] = len(new)
    return merged + new, stats


def _clamp(value: object) -> float:
    try:
        return min(1.0, max(0.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def describe(meta: dict) -> str:
    cost = meta.get("cost_usd", 0.0)
    return (
        f"LLM {meta['model']}: строк {meta['strings_answered']}/{meta['strings_selected']}, "
        f"запросов {meta['requests']} (+{meta['cached_requests']} из кеша), "
        f"токенов {meta['input_tokens']}+{meta['output_tokens']}, ${cost:.4f}"
        f"{' (бесплатный тариф, списано $0)' if meta.get('free_tier') else ''}; "
        f"предложений {meta['suggestions_added']}, отброшено кодом {meta['suggestions_rejected']}, "
        f"снято ложных {meta['dismissed']}, новых находок {meta['new_findings']}"
    )
