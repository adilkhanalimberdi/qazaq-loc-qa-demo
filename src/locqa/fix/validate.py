"""Checks that a translated ARB is safe to ship: placeholders and ICU match the source,
no keys were lost or reordered, every changed string carries the human-review flag, and,
when Flutter is installed, `flutter gen-l10n` compiles it."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from locqa.arb import icu
from locqa.arb.align import Pair
from locqa.arb.parser import ArbDocument
from locqa.checks.base import CheckContext
from locqa.checks.placeholder_mismatch import PlaceholderMismatchCheck
from locqa.checks.plural_mismatch import PluralMismatchCheck

REVIEW_FLAG = "x-reviewed_by_human"


def text_problems(key: str, source: str, text: str, ctx: CheckContext) -> list[str]:
    """Why `text` cannot replace the translation of `source`: placeholder, tag or ICU errors."""
    pair = Pair(key=key, source=source, target=text, section=None, source_line=0, target_line=0)
    problems = []
    for check in (PlaceholderMismatchCheck(), PluralMismatchCheck()):
        problems += [f.evidence for f in check.run([pair], ctx)]
    try:
        icu.parse(text)
    except icu.IcuSyntaxError as e:
        if not any("ICU" in p for p in problems):
            problems.append(f"ICU-синтаксис сломан: {e}")
    return problems


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked: int = 0
    changed: int = 0
    flutter: str = "не запускался"

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(
    source: ArbDocument,
    target: ArbDocument,
    ctx: CheckContext,
    original: ArbDocument | None = None,
) -> ValidationResult:
    result = ValidationResult()
    src = source.strings()
    tgt = target.strings()
    orig = original.strings() if original is not None else None
    for key, entry in tgt.items():
        if key not in src:
            continue
        result.checked += 1
        # Problems that were already in the original file are not regressions of the fix.
        unchanged = orig is not None and key in orig and orig[key].value == entry.value
        bucket = result.warnings if unchanged else result.errors
        for problem in text_problems(key, src[key].value, entry.value, ctx):
            bucket.append(f"{key}: {problem}")

    if orig is not None:
        lost = [k for k in orig if k not in tgt]
        if lost:
            result.errors.append(f"потеряны ключи: {', '.join(lost)}")
        added = [k for k in tgt if k not in orig]
        foreign = [k for k in added if k not in src]
        if foreign:
            result.errors.append(f"добавлены ключи, которых нет в исходнике: {', '.join(foreign)}")
        kept = [k for k in tgt if k in orig]
        if kept != [k for k in orig if k in tgt]:
            result.errors.append("порядок существующих ключей изменился")
        meta = target.metadata()
        changed = [k for k in tgt if k not in orig or tgt[k].value != orig[k].value]
        result.changed = len(changed)
        unflagged = [k for k in changed if meta.get(k, {}).get(REVIEW_FLAG) is not True]
        if unflagged:
            result.errors.append(
                f"изменённые строки без флага {REVIEW_FLAG}: {', '.join(unflagged)}"
            )
    return result


def run_flutter_gen_l10n(source_path: Path, target_path: Path) -> tuple[bool | None, str]:
    """Compile the pair with `flutter gen-l10n` in a throwaway project.
    Returns (None, reason) when Flutter is not installed."""
    flutter = shutil.which("flutter")
    if flutter is None:
        return None, "flutter не найден в PATH, проверка компиляции пропущена"
    with tempfile.TemporaryDirectory(prefix="locqa-l10n-") as tmp:
        root = Path(tmp)
        arb_dir = root / "lib" / "l10n"
        arb_dir.mkdir(parents=True)
        shutil.copy(source_path, arb_dir / Path(source_path).name)
        shutil.copy(target_path, arb_dir / Path(target_path).name)
        (root / "pubspec.yaml").write_text(
            "name: locqa_check\nenvironment:\n  sdk: '>=3.0.0 <4.0.0'\n"
            "dependencies:\n  flutter:\n    sdk: flutter\n  flutter_localizations:\n"
            "    sdk: flutter\n  intl: any\nflutter:\n  generate: true\n",
            encoding="utf-8",
        )
        (root / "l10n.yaml").write_text(
            f"arb-dir: lib/l10n\ntemplate-arb-file: {Path(source_path).name}\n"
            "output-localization-file: app_localizations.dart\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [flutter, "gen-l10n"], cwd=root, capture_output=True, text=True, timeout=600
        )
        output = (proc.stdout + proc.stderr).strip()
        return proc.returncode == 0, output[-2000:] or "ok"
