"""On-disk response cache, so a repeated run with the same strings, prompt version and
model costs nothing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from locqa.arb.writer import write_text


class ResponseCache:
    def __init__(self, directory: Path | None) -> None:
        self.directory = Path(directory) if directory else None

    @staticmethod
    def key(model: str, prompt_version: str, system: str, user: str) -> str:
        blob = json.dumps([model, prompt_version, system, user], ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, key: str) -> str | None:
        if self.directory is None:
            return None
        path = self.directory / f"{key}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))["text"]
        except (FileNotFoundError, KeyError, ValueError):
            return None

    def put(self, key: str, text: str) -> None:
        if self.directory is not None:
            write_text(
                self.directory / f"{key}.json", json.dumps({"text": text}, ensure_ascii=False)
            )
