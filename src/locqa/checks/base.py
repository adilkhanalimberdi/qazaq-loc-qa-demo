"""Common interface for checks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import ClassVar

from locqa.arb.align import Pair
from locqa.config import Config
from locqa.glossary import Glossary
from locqa.models import Finding, IssueType


@dataclass
class CheckContext:
    source_lang: str
    target_lang: str
    config: Config = field(default_factory=Config)
    glossary: Glossary | None = None


class Check(ABC):
    issue_type: ClassVar[IssueType]

    @property
    def name(self) -> str:
        return self.issue_type.value

    @abstractmethod
    def run(self, pairs: Sequence[Pair], ctx: CheckContext) -> list[Finding]: ...
