"""Order-preserving ARB parser.

ARB files are JSON objects, but real-world files repeat keys (most notably "@@comment",
which splits the file into sections), so json.load() would silently keep only the last
value. This parser scans the top-level object member by member and records, for each
member, the decoded value, the exact raw literal and its character offsets. The writer
uses those offsets to change one value without touching any other byte.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from locqa.errors import InputError

SECTION_KEY = "@@comment"
LOCALE_KEY = "@@locale"

_WS = " \t\n\r"
_decoder = json.JSONDecoder()


@dataclass(frozen=True)
class ArbEntry:
    key: str
    value: Any  # str for translatable strings, dict for "@key" metadata
    raw: str  # value literal exactly as written in the file
    start: int  # offset of raw in the document text (characters)
    end: int
    line: int  # 1-based line where the value starts
    section: str | None  # value of the closest "@@comment" above, None before the first one
    index: int  # position among top-level members

    @property
    def is_string(self) -> bool:
        return not self.key.startswith("@")


@dataclass
class ArbDocument:
    text: str
    members: list[ArbEntry]
    path: Path | None = None

    @property
    def name(self) -> str:
        return str(self.path) if self.path else "<text>"

    def locale(self) -> str | None:
        entries = [m for m in self.members if m.key == LOCALE_KEY and isinstance(m.value, str)]
        return entries[-1].value if entries else None

    @cached_property
    def _strings(self) -> dict[str, ArbEntry]:
        effective = {m.key: m for m in self.members if m.is_string}  # last occurrence wins
        return dict(sorted(effective.items(), key=lambda kv: kv[1].index))

    def strings(self) -> dict[str, ArbEntry]:
        """Translatable keys in file order; for duplicates the last occurrence wins,
        as with json.load and flutter gen-l10n."""
        return self._strings

    def metadata(self) -> dict[str, dict]:
        """ "@key" metadata objects keyed by the plain key (without "@")."""
        return {
            m.key[1:]: m.value
            for m in self.members
            if m.key.startswith("@") and not m.key.startswith("@@") and isinstance(m.value, dict)
        }

    def duplicates(self) -> dict[str, list[ArbEntry]]:
        """Translatable keys that occur more than once, with all occurrences in file order."""
        seen: dict[str, list[ArbEntry]] = {}
        for m in self.members:
            if m.is_string:
                seen.setdefault(m.key, []).append(m)
        return {k: v for k, v in seen.items() if len(v) > 1}

    def comments(self) -> list[ArbEntry]:
        return [m for m in self.members if m.key == SECTION_KEY]


def parse_arb(path: Path) -> ArbDocument:
    path = Path(path)
    try:
        # newline="" keeps CRLF/LF exactly as in the file so offsets match the bytes on disk.
        with path.open(encoding="utf-8", newline="") as f:
            text = f.read()
    except FileNotFoundError as e:
        raise InputError(f"файл не найден: {path}") from e
    except UnicodeDecodeError as e:
        raise InputError(f"{path}: файл не в UTF-8 ({e.reason} на байте {e.start})") from e
    except OSError as e:
        raise InputError(f"{path}: не удалось прочитать файл: {e}") from e
    return parse_arb_text(text, path)


def parse_arb_text(text: str, path: Path | None = None) -> ArbDocument:
    name = str(path) if path else "<text>"
    scanner = _Scanner(text, name)
    return ArbDocument(text=text, members=scanner.members(), path=path)


class _Scanner:
    def __init__(self, text: str, name: str) -> None:
        self.text = text
        self.name = name
        self.pos = 1 if text.startswith("﻿") else 0
        self.line = 1
        self._line_pos = 0  # offset up to which self.line has been counted

    def _line_at(self, offset: int) -> int:
        # Offsets only grow during the scan, so count newlines incrementally.
        self.line += self.text.count("\n", self._line_pos, offset)
        self._line_pos = offset
        return self.line

    def _error(self, msg: str, offset: int) -> InputError:
        line = self.text.count("\n", 0, offset) + 1
        col = offset - (self.text.rfind("\n", 0, offset) + 1) + 1
        return InputError(f"{self.name}: некорректный ARB, строка {line}, столбец {col}: {msg}")

    def _skip_ws(self) -> None:
        text, pos = self.text, self.pos
        while pos < len(text) and text[pos] in _WS:
            pos += 1
        self.pos = pos

    def _expect(self, ch: str) -> None:
        self._skip_ws()
        if self.pos >= len(self.text) or self.text[self.pos] != ch:
            found = self.text[self.pos] if self.pos < len(self.text) else "конец файла"
            raise self._error(f"ожидался '{ch}', найдено '{found}'", self.pos)
        self.pos += 1

    def members(self) -> list[ArbEntry]:
        text = self.text
        self._expect("{")
        entries: list[ArbEntry] = []
        section: str | None = None
        self._skip_ws()
        if self.pos < len(text) and text[self.pos] == "}":
            self.pos += 1
        else:
            while True:
                self._skip_ws()
                if self.pos >= len(text) or text[self.pos] != '"':
                    raise self._error("ожидался ключ в кавычках", self.pos)
                try:
                    key, self.pos = json.decoder.scanstring(text, self.pos + 1)
                except json.JSONDecodeError as e:
                    raise self._error(e.msg, e.pos) from e
                self._expect(":")
                self._skip_ws()
                start = self.pos
                try:
                    value, end = _decoder.raw_decode(text, start)
                except json.JSONDecodeError as e:
                    raise self._error(e.msg, e.pos) from e
                if not key.startswith("@") and not isinstance(value, str):
                    raise self._error(f"значение ключа '{key}' должно быть строкой", start)
                if key == SECTION_KEY and isinstance(value, str):
                    section = value
                entries.append(
                    ArbEntry(
                        key=key,
                        value=value,
                        raw=text[start:end],
                        start=start,
                        end=end,
                        line=self._line_at(start),
                        section=section,
                        index=len(entries),
                    )
                )
                self.pos = end
                self._skip_ws()
                if self.pos < len(text) and text[self.pos] == ",":
                    self.pos += 1
                    continue
                self._expect("}")
                break
        self._skip_ws()
        if self.pos != len(text):
            raise self._error("лишние данные после закрывающей скобки", self.pos)
        return entries
