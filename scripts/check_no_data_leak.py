"""Fail if strings from the organizers' data/*.arb appear in files that git would commit.

Run before every commit:  python scripts/check_no_data_leak.py
Without a data/ folder (CI, fresh clone) it exits 0 with a note.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from locqa.arb.parser import parse_arb  # noqa: E402


def committable_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return [ROOT / p for p in out.split("\0") if p]


def needles(data_dir: Path, min_value: int, min_key: int) -> dict[str, str]:
    """needle -> where it comes from."""
    found: dict[str, str] = {}
    for arb in sorted(data_dir.glob("*.arb")):
        doc = parse_arb(arb)
        for entry in doc.members:
            if entry.key.startswith("@"):
                continue
            value = entry.value.strip()
            if len(value) >= min_value:
                found.setdefault(value, f"{arb.name}:{entry.line} value")
                found.setdefault(entry.raw[1:-1].strip(), f"{arb.name}:{entry.line} raw value")
            if len(entry.key) >= min_key:
                found.setdefault(entry.key, f"{arb.name}:{entry.line} key")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--min-value", type=int, default=12, help="min length of values to look for"
    )
    parser.add_argument("--min-key", type=int, default=12, help="min length of keys to look for")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not args.data.is_dir():
        print(f"{args.data} не найдена, проверять нечего.")
        return 0
    data_dir = args.data.resolve()
    targets = needles(data_dir, args.min_value, args.min_key)
    leaks = 0
    for path in committable_files():
        if data_dir in path.resolve().parents or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary files
        for needle, origin in targets.items():
            if needle in text:
                leaks += 1
                print(
                    f"{path.relative_to(ROOT)}: найдено совпадение с {origin} (длина {len(needle)})"
                )
    if leaks:
        print(f"Найдено совпадений: {leaks}. Уберите их перед коммитом.")
        return 1
    print(f"Чисто: {len(targets)} строк из {data_dir.name}/ не встречаются в файлах для коммита.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
