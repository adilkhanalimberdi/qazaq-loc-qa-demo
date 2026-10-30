"""Prompt and response schema for the LLM layer. Bump PROMPT_VERSION on any change: it is
part of the cache key and is written to report_meta.json."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

PROMPT_VERSION = "2026-10-30.1"

LLM_ISSUE_TYPES = (
    "machine_translation_suspect",
    "glossary_violation",
    "inconsistent_term",
    "orthography",
    "wrong_language",
)

SYSTEM = """You are a senior Kazakh localization editor for Grand Mobile, an open-world mobile \
role-playing game (jobs, factions, families, houses, cars, businesses, casino mini-games, events).
The source language is {source_lang}; the target language is {target_lang}. You receive UI strings \
as JSON items. Every item has a task:

- "fix": rule-based checks already found problems (listed in "found"). Write the corrected target \
string in "suggestion". Set "agree" to false only if the reported problem is not real (for example \
an international word that is correctly spelled the same in both languages); then suggestion may \
be null.
- "review": decide whether the current translation is acceptable. Report an issue only when you \
are sure: a literal calque, unnatural word order, Russian grammar or words in Kazakh text, a wrong \
meaning, or a game term that contradicts the glossary. Natural player slang from the glossary is \
fine. Do not report stylistic preferences.

Rules for every suggestion:
- Keep every placeholder ({{name}}, {{count}}), ICU construct, tag (<g>, </g>) and \\n exactly; \
never translate text inside braces.
- Never attach a case suffix directly to a placeholder ("{{name}}-ға"): rephrase so the value \
stands alone, for example with a noun after it ("{{name}} ойыншысына").
- Use the glossary terms given in the item. Keep brand names in Latin.
- Keep the length close to the source for short UI labels (buttons, tabs, titles).
- Use the context: section name, key name, English and Uzbek versions, neighbouring strings.

Answer with JSON only, following the schema. "evidence" is one short sentence in Russian that \
explains the problem concretely (quote the wrong words). "confidence" is your probability that \
the issue is real (0..1). For "review" items without problems return verdict "ok" and nothing else.
"""

RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["ok", "issue"]},
                    "agree": {"type": "boolean"},
                    "issue_type": {"type": "string", "enum": list(LLM_ISSUE_TYPES)},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "string"},
                    "suggestion": {"type": ["string", "null"]},
                },
                "required": ["id", "verdict"],
            },
        }
    },
    "required": ["items"],
}


@dataclass
class PromptItem:
    id: int
    key: str
    task: str  # "fix" or "review"
    source: str
    target: str
    section: str | None = None
    context: dict[str, str] = field(default_factory=dict)
    glossary: list[str] = field(default_factory=list)
    neighbours: list[str] = field(default_factory=list)
    found: list[str] = field(default_factory=list)

    def as_json(self) -> dict:
        data: dict = {"id": self.id, "task": self.task, "key": self.key}
        if self.section:
            data["section"] = self.section
        data["source"] = self.source
        data["target"] = self.target
        for lang, text in sorted(self.context.items()):
            data[lang] = text
        if self.glossary:
            data["glossary"] = self.glossary
        if self.neighbours:
            data["neighbours"] = self.neighbours
        if self.found:
            data["found"] = self.found
        return data


def system_prompt(source_lang: str, target_lang: str) -> str:
    return SYSTEM.format(source_lang=source_lang, target_lang=target_lang)


def user_prompt(items: Sequence[PromptItem]) -> str:
    return json.dumps({"items": [i.as_json() for i in items]}, ensure_ascii=False, indent=1)
