"""locqa command line.

Exit codes: 0 no findings at or above --min-severity, 1 findings present,
2 input error, 3 LLM error (rule results are still written).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from locqa import __version__
from locqa.arb import parse_arb, write_text
from locqa.checks import CheckContext
from locqa.errors import InputError, LLMError, LocqaError
from locqa.fix.apply import apply_review, mark_reviewed
from locqa.fix.review_sheet import build_rows, read_review, write_review
from locqa.fix.validate import run_flutter_gen_l10n
from locqa.fix.validate import validate as validate_arb
from locqa.llm.client import load_env, make_client
from locqa.llm.layer import LLMOptions, describe
from locqa.models import Severity
from locqa.pipeline import detect_lang, run_check, run_llm_stage
from locqa.report.html_writer import write_html
from locqa.report.json_writer import (
    load_meta,
    load_report,
    meta_path_for,
    write_meta,
    write_report,
)

DEFAULT_MODEL = "gemini-2.5-flash"

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_INPUT = 2
EXIT_LLM = 3

app = typer.Typer(
    name="locqa",
    help="Проверка качества локализации ARB-файлов: эталон против перевода.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


def _fail(err: LocqaError) -> NoReturn:
    typer.echo(f"Ошибка: {err}", err=True)
    raise typer.Exit(err.exit_code)


def _split_names(value: str | None) -> list[str]:
    return [n.strip() for n in value.split(",") if n.strip()] if value else []


def _version(value: bool) -> None:
    if value:
        typer.echo(f"locqa {__version__}")
        raise typer.Exit(EXIT_OK)


@app.callback()
def _root(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Версия и выход.")
    ] = False,
) -> None:
    pass


@app.command()
def check(
    source: Annotated[Path, typer.Option(help="Эталонный ARB (например intl_ru.arb).")],
    target: Annotated[Path, typer.Option(help="Проверяемый ARB (например intl_kk.arb).")],
    out: Annotated[
        Path, typer.Option(help="Куда писать report.json; рядом пишется report_meta.json.")
    ] = Path("out/report.json"),
    glossary: Annotated[Path | None, typer.Option(help="glossary.csv.")] = None,
    html: Annotated[Path | None, typer.Option(help="Записать ещё и HTML-отчёт.")] = None,
    context: Annotated[
        list[Path] | None,
        typer.Option(
            help="Доп. ARB для контекста LLM, можно повторять: --context a.arb --context b.arb."
        ),
    ] = None,
    only: Annotated[str | None, typer.Option(help="Только эти проверки, через запятую.")] = None,
    skip: Annotated[
        str | None, typer.Option(help="Пропустить эти проверки, через запятую.")
    ] = None,
    llm: Annotated[
        bool,
        typer.Option("--llm/--no-llm", help="LLM: предложения исправлений и машинный перевод."),
    ] = False,
    llm_model: Annotated[
        str | None,
        typer.Option(help=f"Модель LLM (по умолчанию LOCQA_LLM_MODEL или {DEFAULT_MODEL})."),
    ] = None,
    llm_scope: Annotated[
        str,
        typer.Option(help="suspects: находки правил и подозрительные строки; all: все строки."),
    ] = "suspects",
    max_llm_strings: Annotated[int | None, typer.Option(min=0, help="Лимит строк для LLM.")] = None,
    budget_usd: Annotated[
        float | None, typer.Option(min=0.0, help="Остановить LLM, когда стоимость дойдёт до X USD.")
    ] = None,
    llm_cache: Annotated[
        Path | None, typer.Option(help="Папка кеша ответов LLM (по умолчанию рядом с отчётом).")
    ] = None,
    min_severity: Annotated[
        Severity, typer.Option(case_sensitive=False, help="Не писать находки ниже этого уровня.")
    ] = Severity.LOW,
    lang: Annotated[
        str | None, typer.Option(help="Язык перевода; по умолчанию из @@locale или имени файла.")
    ] = None,
) -> None:
    """Найти ошибки локализации и записать report.json."""
    try:
        result = run_check(
            source,
            target,
            glossary_path=glossary,
            context_paths=context or [],
            only=_split_names(only) or None,
            skip=_split_names(skip),
            min_severity=min_severity,
            lang=lang,
        )
    except LocqaError as e:
        _fail(e)

    for w in result.warnings:
        typer.echo(f"Предупреждение: {w}", err=True)

    llm_error: LLMError | None = None
    if llm:
        if llm_scope not in ("suspects", "all"):
            _fail(InputError("--llm-scope: suspects или all"))
        load_env()
        model = llm_model or os.environ.get("LOCQA_LLM_MODEL") or DEFAULT_MODEL
        options = LLMOptions(
            model=model,
            scope=llm_scope,
            max_strings=max_llm_strings,
            budget_usd=budget_usd,
            batch_size=int(os.environ.get("LOCQA_LLM_BATCH") or 20),
            cache_dir=llm_cache or out.parent / ".llm_cache",
        )
        try:
            client = make_client(model)
            stopped = run_llm_stage(result, client, options)
            if stopped:
                llm_error = LLMError(f"LLM-слой остановлен: {stopped}; сохранено то, что успели")
        except LLMError as e:
            llm_error = LLMError(f"{e}; результаты правил сохранены")
        if result.meta.llm:
            typer.echo(describe(result.meta.llm))
            cost = json.dumps(result.meta.llm, ensure_ascii=False, indent=2) + "\n"
            write_text(out.with_name("cost.json"), cost)

    write_report(result.findings, out)
    meta_path = meta_path_for(out)
    write_meta(result.meta, meta_path)
    counts = ", ".join(f"{k}: {v}" for k, v in sorted(result.meta.counts_by_type.items())) or "нет"
    typer.echo(f"Находок: {len(result.findings)} ({counts}). Отчёт: {out}, сводка: {meta_path}")
    if html is not None:
        write_html(result.findings, html, result.meta)
        typer.echo(f"HTML-отчёт: {html}")
    if llm_error is not None:
        _fail(llm_error)
    raise typer.Exit(EXIT_FINDINGS if result.findings else EXIT_OK)


@app.command("review-sheet")
def review_sheet(
    report: Annotated[Path, typer.Option(help="report.json.")],
    out: Annotated[Path, typer.Option(help="review.csv для носителя.")] = Path("out/review.csv"),
    min_severity: Annotated[
        Severity, typer.Option(case_sensitive=False, help="Только находки не ниже уровня.")
    ] = Severity.LOW,
    min_confidence: Annotated[
        float, typer.Option(min=0.0, max=1.0, help="Только находки с confidence не ниже.")
    ] = 0.0,
    only: Annotated[str | None, typer.Option(help="Только эти типы, через запятую.")] = None,
    skip: Annotated[str | None, typer.Option(help="Без этих типов, через запятую.")] = None,
    chunk: Annotated[
        int | None, typer.Option(min=1, help="Разбить на файлы по N строк: review_001.csv...")
    ] = None,
) -> None:
    """Сделать review.csv для носителя: одна строка на ключ, сначала high."""
    try:
        findings = load_report(report)
    except LocqaError as e:
        _fail(e)
    rows = build_rows(
        findings,
        min_severity=min_severity,
        min_confidence=min_confidence,
        only=_split_names(only),
        skip=_split_names(skip),
    )
    paths = write_review(rows, out, chunk)
    with_suggestion = sum(1 for r in rows if r.suggestion)
    typer.echo(
        f"Строк для проверки: {len(rows)} (с предложением: {with_suggestion}). "
        f"Файлы: {', '.join(map(str, paths))}"
    )
    typer.echo(
        "Заполните decision: accept (взять suggestion или final_text), edit (свой текст в "
        "final_text), reject. Строки без decision не применяются.",
        err=True,
    )


@app.command()
def apply(
    source: Annotated[Path, typer.Option(help="Эталонный ARB (для проверки плейсхолдеров).")],
    target: Annotated[Path, typer.Option(help="Исходный перевод (intl_kk.arb).")],
    review: Annotated[
        list[Path], typer.Option(help="Заполненный review.csv, можно повторять для частей.")
    ],
    out: Annotated[Path, typer.Option(help="Исправленный ARB.")] = Path("out/intl_kk_fixed.arb"),
    log: Annotated[Path, typer.Option(help="Журнал изменений.")] = Path("out/fixed_review.json"),
    report: Annotated[
        Path | None,
        typer.Option(help="report.json: отметить reviewed_by_human у применённых ключей."),
    ] = None,
    lang: Annotated[str | None, typer.Option(help="Язык перевода.")] = None,
) -> None:
    """Внести в ARB только строки с decision accept или edit, с флагом проверки человеком."""
    try:
        src_doc = parse_arb(source)
        tgt_doc = parse_arb(target)
        rows = [row for path in review for row in read_review(path)]
        findings = load_report(report) if report is not None else None
    except LocqaError as e:
        _fail(e)
    ctx = CheckContext(
        source_lang=detect_lang(src_doc, "ru"), target_lang=lang or detect_lang(tgt_doc, "kk")
    )
    result = apply_review(tgt_doc, src_doc, rows, ctx)
    write_text(out, result.text)
    log_data = [c.as_log() for c in result.changes]
    write_text(log, json.dumps(log_data, ensure_ascii=False, indent=2) + "\n")
    if report is not None and findings is not None:
        updated = mark_reviewed(findings, result.changes)
        write_report(updated, report)
        html = report.with_suffix(".html")
        if html.exists():
            write_html(updated, html, load_meta(meta_path_for(report)))
        typer.echo(f"Отмечено reviewed_by_human в {report}")
    for reason in result.refused:
        typer.echo(f"Отклонено: {reason}", err=True)
    typer.echo(
        f"Применено: {len(result.changes)}, отклонено: {len(result.refused)}, "
        f"без решения или без изменений: {result.skipped}. Файл: {out}, журнал: {log}"
    )
    raise typer.Exit(EXIT_FINDINGS if result.refused else EXIT_OK)


@app.command()
def validate(
    source: Annotated[Path, typer.Option(help="Эталонный ARB.")],
    target: Annotated[Path, typer.Option(help="Проверяемый ARB (например intl_kk_fixed.arb).")],
    original: Annotated[
        Path | None,
        typer.Option(help="Перевод до исправлений: проверить потерю ключей, порядок и флаги."),
    ] = None,
    flutter: Annotated[
        bool,
        typer.Option("--flutter/--no-flutter", help="Запустить flutter gen-l10n, если найден."),
    ] = True,
    lang: Annotated[str | None, typer.Option(help="Язык перевода.")] = None,
) -> None:
    """Проверить плейсхолдеры, ICU, потерю ключей и флаги проверки человеком."""
    try:
        src_doc = parse_arb(source)
        tgt_doc = parse_arb(target)
        orig_doc = parse_arb(original) if original else None
    except LocqaError as e:
        _fail(e)
    ctx = CheckContext(
        source_lang=detect_lang(src_doc, "ru"), target_lang=lang or detect_lang(tgt_doc, "kk")
    )
    result = validate_arb(src_doc, tgt_doc, ctx, orig_doc)
    for w in result.warnings:
        typer.echo(f"Предупреждение (было и до исправлений): {w}", err=True)
    for e in result.errors:
        typer.echo(f"Ошибка: {e}", err=True)
    if flutter:
        ok, output = run_flutter_gen_l10n(source, target)
        if ok is None:
            typer.echo(output, err=True)
        elif not ok:
            result.errors.append("flutter gen-l10n завершился с ошибкой")
            typer.echo(f"flutter gen-l10n:\n{output}", err=True)
        else:
            typer.echo("flutter gen-l10n: ok")
    status = "OK" if result.ok else f"ошибок: {len(result.errors)}"
    changed = f", изменено строк: {result.changed}" if original else ""
    typer.echo(
        f"Проверено строк: {result.checked}{changed}, "
        f"предупреждений: {len(result.warnings)}. {status}"
    )
    raise typer.Exit(EXIT_OK if result.ok else EXIT_FINDINGS)


@app.command()
def report(
    report: Annotated[Path, typer.Option(help="report.json.")],
    html: Annotated[Path, typer.Option(help="Куда писать HTML.")] = Path("out/report.html"),
) -> None:
    """Пересобрать HTML-отчёт из report.json (и report_meta.json рядом, если есть)."""
    try:
        findings = load_report(report)
    except LocqaError as e:
        _fail(e)
    write_html(findings, html, load_meta(meta_path_for(report)))
    typer.echo(f"HTML-отчёт: {html} ({len(findings)} находок)")


def _force_utf8_output() -> None:
    # Russian and Kazakh output crashes on legacy Windows consoles (cp1252/cp866).
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _force_utf8_output()
    app()
