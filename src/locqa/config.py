"""Tunable thresholds and allowlists. Nothing here is tied to a specific language pair."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Config:
    # same_as_source: keys and exact texts that may legitimately equal the source
    # (brands, names, service symbols). Matched after strip().
    same_as_source_allow_keys: set[str] = field(default_factory=set)
    same_as_source_allow_texts: set[str] = field(default_factory=set)
    # A single-word identical string is more often a legitimate loanword.
    same_as_source_single_word_confidence: float = 0.4
    same_as_source_multi_word_confidence: float = 0.9
    # A single word with source-language inflection ("Напугать") is not a loanword.
    same_as_source_inflected_confidence: float = 0.85
    # placeholder_mismatch: report a different number of \n on its own (low severity).
    report_newline_mismatch: bool = False

    # length_overflow: only short source strings are UI elements that can overflow.
    length_max_source_chars: int = 25
    # Keys that name a button, tab or heading get stricter limits.
    length_ui_key_pattern: str = r"(?i)(button|btn|tab|title|header|label|caption)"
    length_ratio: float = 2.5
    length_min_extra_chars: int = 10
    length_ui_ratio: float = 2.0
    length_ui_min_extra_chars: int = 8
    length_high_ratio: float = 3.5
    # A trailing phrase of this many words, absent in the source and repeated in several
    # overflowing strings, looks like boilerplate appended by a machine ("... үшін басыңыз").
    length_tail_words: int = 3

    # orthography: words shorter than this are not compared with their lookalike variants.
    orthography_min_word_len: int = 4
    # The correct form occurring this many times more often gives high confidence.
    orthography_strong_ratio: int = 5

    # glossary_violation: the term is absent from the translation (may be a paraphrase).
    glossary_missing_confidence: float = 0.7
    # Sources longer than this are descriptions: a missing term is reported as low.
    glossary_long_source_words: int = 8

    # inconsistent_term: the reference translation needs this many keys behind it,
    # and very short sources ("От", "ru") are too ambiguous to compare.
    inconsistent_min_majority: int = 2
    inconsistent_min_source_chars: int = 4
    # Longer sources are phrases whose wording legitimately varies; terms and labels are short.
    inconsistent_max_source_words: int = 4
