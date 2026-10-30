"""Minimal ICU MessageFormat parser for ARB strings.

Supports simple arguments ({name}), typed arguments ({n, number}) and complex arguments
(plural, select, selectordinal) with nested messages and "#". Apostrophe quoting is off by
default, matching flutter gen-l10n (use-escaping: false).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

COMPLEX_TYPES = frozenset({"plural", "select", "selectordinal"})
PLURAL_TYPES = frozenset({"plural", "selectordinal"})

_TAG_RE = re.compile(r"</?[A-Za-z][\w-]*(?:\s[^<>]*)?/?>")
_FALLBACK_ARG_RE = re.compile(r"\{\s*([^{}\s,]+)\s*[,}]")


class IcuSyntaxError(ValueError):
    def __init__(self, msg: str, pos: int) -> None:
        super().__init__(f"{msg} (позиция {pos})")
        self.pos = pos


@dataclass
class Argument:
    name: str
    type: str | None = None
    style: str | None = None
    offset: int = 0
    options: dict[str, list[Node]] = field(default_factory=dict)

    @property
    def is_complex(self) -> bool:
        return self.type in COMPLEX_TYPES


@dataclass(frozen=True)
class Pound:
    """'#' inside a plural branch."""


Node = str | Argument | Pound


def parse(message: str, *, use_escaping: bool = False) -> list[Node]:
    parser = _Parser(message, use_escaping)
    nodes = parser.message(in_plural=False)
    if parser.pos != len(message):
        raise IcuSyntaxError("лишняя закрывающая скобка '}'", parser.pos)
    return nodes


def iter_arguments(nodes: list[Node]) -> Iterator[Argument]:
    for node in nodes:
        if isinstance(node, Argument):
            yield node
            for branch in node.options.values():
                yield from iter_arguments(branch)


def extract_arguments(message: str) -> Counter[str]:
    """Argument names with occurrence counts. Falls back to a regex on syntax errors,
    so a broken string still yields comparable placeholders."""
    try:
        return Counter(arg.name for arg in iter_arguments(parse(message)))
    except IcuSyntaxError:
        return Counter(_FALLBACK_ARG_RE.findall(message))


def has_complex_argument(message: str) -> bool:
    try:
        return any(arg.is_complex for arg in iter_arguments(parse(message)))
    except IcuSyntaxError:
        return False


def extract_tags(message: str) -> Counter[str]:
    """Markup tags such as <g>, </g>, <font color=...>, counted as written."""
    return Counter(_TAG_RE.findall(message))


def count_newlines(message: str) -> int:
    return message.count("\n")


class _Parser:
    def __init__(self, text: str, use_escaping: bool) -> None:
        self.text = text
        self.pos = 0
        self.use_escaping = use_escaping

    def _peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _skip_ws(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _expect(self, ch: str) -> None:
        if self._peek() != ch:
            found = self._peek() or "конец строки"
            raise IcuSyntaxError(f"ожидался '{ch}', найдено '{found}'", self.pos)
        self.pos += 1

    def _token(self) -> str:
        start = self.pos
        while self.pos < len(self.text) and not (
            self.text[self.pos].isspace() or self.text[self.pos] in "{},"
        ):
            self.pos += 1
        return self.text[start : self.pos]

    def message(self, in_plural: bool) -> list[Node]:
        nodes: list[Node] = []
        buf: list[str] = []

        def flush() -> None:
            if buf:
                nodes.append("".join(buf))
                buf.clear()

        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch == "{":
                flush()
                nodes.append(self.argument())
            elif ch == "}":
                break
            elif ch == "#" and in_plural:
                flush()
                nodes.append(Pound())
                self.pos += 1
            elif ch == "'" and self.use_escaping:
                buf.append(self._quoted(in_plural))
            else:
                buf.append(ch)
                self.pos += 1
        flush()
        return nodes

    def _quoted(self, in_plural: bool) -> str:
        nxt = self.text[self.pos + 1 : self.pos + 2]
        if nxt == "'":
            self.pos += 2
            return "'"
        if nxt in ("{", "}") or (nxt == "#" and in_plural):
            end = self.text.find("'", self.pos + 1)
            if end == -1:
                end = len(self.text)
            literal = self.text[self.pos + 1 : end].replace("''", "'")
            self.pos = min(end + 1, len(self.text))
            return literal
        self.pos += 1
        return "'"

    def argument(self) -> Argument:
        start = self.pos
        self._expect("{")
        self._skip_ws()
        name = self._token()
        if not name:
            raise IcuSyntaxError("пустое имя аргумента", start)
        self._skip_ws()
        if self._peek() == "}":
            self.pos += 1
            return Argument(name=name)
        self._expect(",")
        self._skip_ws()
        arg_type = self._token()
        if not arg_type:
            raise IcuSyntaxError(f"пустой тип у аргумента '{name}'", self.pos)
        arg = Argument(name=name, type=arg_type)
        self._skip_ws()
        if self._peek() == "}":
            self.pos += 1
            return arg
        self._expect(",")
        if arg.is_complex:
            self._options(arg)
        else:
            style_start = self.pos
            while self._peek() not in ("}", ""):
                self.pos += 1
            arg.style = self.text[style_start : self.pos].strip()
        self._skip_ws()
        if self._peek() != "}":
            raise IcuSyntaxError(f"незакрытый аргумент '{name}'", start)
        self.pos += 1
        return arg

    def _options(self, arg: Argument) -> None:
        in_plural = arg.type in PLURAL_TYPES
        while True:
            self._skip_ws()
            if self._peek() in ("}", ""):
                break
            selector = self._token()
            if not selector:
                raise IcuSyntaxError(f"пустой селектор в '{arg.name}'", self.pos)
            if in_plural and selector.startswith("offset:"):
                try:
                    arg.offset = int(selector.removeprefix("offset:"))
                except ValueError as e:
                    raise IcuSyntaxError(f"некорректный offset в '{arg.name}'", self.pos) from e
                continue
            self._skip_ws()
            branch_start = self.pos
            self._expect("{")
            branch = self.message(in_plural)
            if self._peek() != "}":
                raise IcuSyntaxError(f"незакрытая ветка '{selector}' в '{arg.name}'", branch_start)
            self.pos += 1
            if selector in arg.options:
                raise IcuSyntaxError(f"повтор селектора '{selector}' в '{arg.name}'", branch_start)
            arg.options[selector] = branch
