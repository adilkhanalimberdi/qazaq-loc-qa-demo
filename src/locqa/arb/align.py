"""Pairs source and target strings by key."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from locqa.arb.parser import ArbDocument


@dataclass(frozen=True)
class Pair:
    key: str
    source: str
    target: str | None  # None when the key is missing in the target file
    section: str | None
    source_line: int
    target_line: int | None
    context: dict[str, str] = field(default_factory=dict)  # lang -> text from --context files


def align(
    source: ArbDocument,
    target: ArbDocument,
    context: Mapping[str, ArbDocument] | None = None,
) -> tuple[list[Pair], list[str]]:
    """Pairs in source order, plus warnings about the target file."""
    context = context or {}
    src = source.strings()
    tgt = target.strings()
    ctx_strings = {lang: doc.strings() for lang, doc in context.items()}

    pairs = []
    for key, s in src.items():
        t = tgt.get(key)
        pairs.append(
            Pair(
                key=key,
                source=s.value,
                target=t.value if t else None,
                section=s.section,
                source_line=s.line,
                target_line=t.line if t else None,
                context={
                    lang: strings[key].value
                    for lang, strings in ctx_strings.items()
                    if key in strings
                },
            )
        )

    warnings = []
    extra = [k for k in tgt if k not in src]
    if extra:
        warnings.append(
            f"{target.name}: {len(extra)} ключ(ей) нет в исходном файле: {', '.join(extra)}"
        )
    for doc in (source, target):
        dups = doc.duplicates()
        conflicting = [k for k, entries in dups.items() if len({e.value for e in entries}) > 1]
        if dups:
            msg = (
                f"{doc.name}: {len(dups)} дублирующихся ключ(ей), используется последнее вхождение"
            )
            if conflicting:
                details = "; ".join(
                    f"{k} (строки {', '.join(str(e.line) for e in dups[k])})" for k in conflicting
                )
                msg += f"; с разными значениями: {details}"
            warnings.append(msg)
    return pairs, warnings
