"""История последних диктовок — чтобы вернуть текст, если вставка ушла не туда."""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

from config import app_data_dir


@dataclass(frozen=True)
class Entry:
    text: str
    at: float

    @property
    def when(self) -> str:
        return time.strftime("%H:%M", time.localtime(self.at))

    def label(self, width: int = 48) -> str:
        flat = " ".join(self.text.split())
        if len(flat) > width:
            flat = flat[: width - 1].rstrip() + "…"
        return f"{self.when}  {flat}"


class History:
    def __init__(self, size: int = 10) -> None:
        self._path = app_data_dir() / "history.json"
        self._items: deque[Entry] = deque(maxlen=max(1, size))
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for item in raw if isinstance(raw, list) else []:
            try:
                self._items.append(Entry(text=str(item["text"]), at=float(item["at"])))
            except (KeyError, TypeError, ValueError):
                continue

    def add(self, text: str) -> None:
        if not text.strip():
            return
        self._items.appendleft(Entry(text=text, at=time.time()))
        self._save()

    def clear(self) -> None:
        self._items.clear()
        self._save()

    def _save(self) -> None:
        try:
            payload = json.dumps([asdict(e) for e in self._items], ensure_ascii=False, indent=1)
            self._path.write_text(payload, encoding="utf-8")
        except OSError as exc:
            print(f"[history] не удалось сохранить: {exc}")

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)
