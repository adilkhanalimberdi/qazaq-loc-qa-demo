"""Surgical ARB writer: replaces individual string values and leaves every other byte as is.

Re-serialising with json.dump would drop repeated "@@comment" markers and normalise
indentation and escapes, so new literals are spliced into the original text instead.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path

from locqa.arb.parser import ArbDocument


def encode_json_string(value: str) -> str:
    """JSON string literal for value: quotes, backslashes and control characters escaped,
    private-use and other invisible characters as \\uXXXX, everything else literal."""
    out = []
    for ch in json.dumps(value, ensure_ascii=False)[1:-1]:
        if unicodedata.category(ch) in ("Co", "Cf", "Cs", "Zl", "Zp"):
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def replace_values(doc: ArbDocument, changes: Mapping[str, str]) -> str:
    """Return doc.text with the effective (last) occurrence of each key set to a new value.

    Raises KeyError for keys that are not translatable strings in doc.
    """
    strings = doc.strings()
    spans = []
    for key, value in changes.items():
        if key not in strings:
            raise KeyError(key)
        entry = strings[key]
        spans.append((entry.start, entry.end, encode_json_string(value)))
    spans.sort()
    parts = []
    pos = 0
    for start, end, literal in spans:
        parts.append(doc.text[pos:start])
        parts.append(literal)
        pos = end
    parts.append(doc.text[pos:])
    return "".join(parts)


def _indent_of(doc: ArbDocument, offset: int) -> str:
    """Leading whitespace of the line that contains offset."""
    line_start = doc.text.rfind("\n", 0, offset) + 1
    line = doc.text[line_start:offset]
    return line[: len(line) - len(line.lstrip(" \t"))]


def _newline(doc: ArbDocument) -> str:
    return "\r\n" if "\r\n" in doc.text else "\n"


def _metadata_literal(value: dict, indent: str, nl: str) -> str:
    """A metadata object in the file's style: one line if small, else indented like the file."""
    one_line = json.dumps(value, ensure_ascii=False)
    if len(one_line) <= 80:
        return one_line
    body = json.dumps(value, ensure_ascii=False, indent=2)
    return body.replace("\n", nl + indent)


def _members_literal(
    key: str, value: str, fields: Mapping[str, object] | None, indent: str, nl: str
) -> str:
    """'"key": "value"' plus '"@key": {...}' on the next line when fields are given."""
    text = f"{json.dumps(key, ensure_ascii=False)}: {encode_json_string(value)}"
    if fields:
        meta = _metadata_literal(dict(fields), indent, nl)
        text += f",{nl}{indent}{json.dumps('@' + key, ensure_ascii=False)}: {meta}"
    return text


def edit_document(
    doc: ArbDocument,
    values: Mapping[str, str] | None = None,
    metadata: Mapping[str, Mapping[str, object]] | None = None,
    new_entries: Sequence[tuple[str, str, str | None]] = (),
) -> str:
    """Return doc.text with surgical edits; all other bytes stay as they are.

    values: new text for existing keys (last occurrence).
    metadata: fields merged into "@key" of each key, created right after the key if absent.
    new_entries: (key, value, anchor) inserted after the anchor key and its metadata, or at the
        top of the object if the anchor is None or absent.
    """
    values = values or {}
    metadata = metadata or {}
    strings = doc.strings()
    meta_entries = {
        m.key[1:]: m for m in doc.members if m.key.startswith("@") and m.key[1:] in strings
    }
    nl = _newline(doc)
    edits: list[tuple[int, int, int, str]] = []  # start, end, order, replacement

    for key, value in values.items():
        if key not in strings:
            raise KeyError(key)
        entry = strings[key]
        edits.append((entry.start, entry.end, 0, encode_json_string(value)))

    for key, fields in metadata.items():
        if key not in strings:
            continue  # new keys get their metadata on insertion
        indent = _indent_of(doc, strings[key].start)
        meta = meta_entries.get(key)
        if meta is not None and isinstance(meta.value, dict):
            merged = {**meta.value, **fields}
            edits.append((meta.start, meta.end, 0, _metadata_literal(merged, indent, nl)))
        else:
            literal = _metadata_literal(dict(fields), indent, nl)
            name = json.dumps("@" + key, ensure_ascii=False)
            end = strings[key].end
            edits.append((end, end, 1, f",{nl}{indent}{name}: {literal}"))

    for order, (key, value, anchor) in enumerate(new_entries, start=2):
        if anchor in strings:
            # After the anchor's own "@anchor" when it directly follows the anchor.
            after = meta_entries.get(anchor)
            follows = after is not None and after.index == strings[anchor].index + 1
            pos = after.end if follows else strings[anchor].end
            indent = _indent_of(doc, strings[anchor].start)
            members = _members_literal(key, value, metadata.get(key), indent, nl)
            edits.append((pos, pos, order, f",{nl}{indent}{members}"))
        elif doc.members and doc.members[0].key.startswith("@@"):
            # After the file header ("@@locale" and friends).
            head = next(
                i
                for i, m in enumerate([*doc.members, None])
                if m is None or not m.key.startswith("@@")
            )
            last = doc.members[head - 1]
            indent = _indent_of(doc, last.start)
            members = _members_literal(key, value, metadata.get(key), indent, nl)
            edits.append((last.end, last.end, order, f",{nl}{indent}{members}"))
        elif doc.members:
            # Before the first member: find the opening quote of its key.
            first = doc.members[0]
            colon = doc.text.rfind(":", 0, first.start)
            pos = doc.text.rfind('"', 0, doc.text.rfind('"', 0, colon))
            indent = _indent_of(doc, first.start)
            members = _members_literal(key, value, metadata.get(key), indent, nl)
            edits.append((pos, pos, order, f"{members},{nl}{indent}"))
        else:
            raise KeyError(f"нет места для вставки {key}: в файле нет ни одного ключа")

    edits.sort(key=lambda e: (e[0], e[2]))
    parts = []
    pos = 0
    for start, end, _, replacement in edits:
        parts.append(doc.text[pos:start])
        parts.append(replacement)
        pos = end
    parts.append(doc.text[pos:])
    return "".join(parts)


def write_text(path: Path, text: str) -> None:
    """Write UTF-8 without newline translation, so LF files stay LF on Windows."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(text)
