"""Журнал диктовок: что сказал Whisper, что из этого сделала модель, сколько это стоило.

История в трее держит десять последних записей и только итоговый текст. По ней
нельзя ответить ни на один вопрос, который возникает при настройке: что модель
изменила, сколько ждали, как часто правка вообще что-то меняет. Журнал пишет всё,
что знает конвейер, — по строке JSON на диктовку.

Формат построчный намеренно: дописывается без перечитывания файла, читается
частями и переживает обрыв записи — битой окажется одна последняя строка, а не
весь журнал.

Эталона у нас нет, и правильность правки журнал не измеряет. Зато он измеряет
объём вмешательства: сколько слов модель тронула. На чистом входе это число
должно быть близко к нулю, и всплеск в нём — первый признак, что модель начала
пересказывать вместо чистки.

Файл лежит рядом с конфигом и содержит всё надиктованное открытым текстом.
Никуда не отправляется, но выключается в настройках: llm/journal -> false.
"""

from __future__ import annotations

import difflib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from config import APP_VERSION, app_data_dir


@dataclass
class Record:
    """Одна диктовка от нажатия клавиши до вставки."""

    at: str
    audio_s: float
    hotkey: str

    version: str = APP_VERSION
    """Какая сборка сделала запись: без этого поля старые записи не отличить."""

    whisper_s: float = 0.0
    stt: str = ""
    """Кто распознавал: «large-v3-turbo · cuda» или облачная модель."""

    raw: str = ""
    """Сырой текст Whisper — то, чего сейчас нигде не сохраняется."""

    llm_model: str = ""
    """Пусто, если модель не звали."""

    style: str = ""
    """Стиль правки: careful, dry или пусто, если модель не звали."""

    skipped: str = ""
    """Почему пропустили правку: «выключена», «слишком коротко», «сырой режим»."""

    llm_s: float = 0.0
    output_tokens: int = 0
    gen_s: float = 0.0
    """Время именно генерации: по нему считается ток/с, не завися от очереди."""

    response: str = ""
    """Ответ модели до вычистки обёрток — по нему видно, что она приписывает."""

    polished: str = ""
    accepted: bool | None = None
    """Прошёл ли ответ проверку на осмысленность. None — модель не звали."""

    error: str = ""

    cloud_quota: str = ""
    """Остатки лимитов облака после этой диктовки, если её правило облако."""

    final: str = ""
    """То, что реально ушло в активное окно."""

    changed_words: int = 0
    raw_words: int = 0
    total_s: float = 0.0


class Journal:
    """Дописывает записи в dictations.jsonl, переживая любые сбои записи."""

    def __init__(self, enabled: bool = True, max_mb: float = 32.0) -> None:
        self.enabled = enabled
        self._max_bytes = int(max_mb * 1024 * 1024)
        self._path = app_data_dir() / "dictations.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def write(self, record: Record) -> None:
        """Сбой журнала не должен стоить человеку продиктованной фразы."""
        if not self.enabled:
            return
        try:
            self._rotate_if_big()
            line = json.dumps(asdict(record), ensure_ascii=False)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            print(f"[journal] не удалось записать: {exc}")

    def _rotate_if_big(self) -> None:
        """При переполнении оставляем ровно одно предыдущее поколение.

        Держать больше незачем: свежие записи ценнее, а место на диске мы обещали
        не занимать. Старое поколение перезаписывается.
        """
        try:
            if self._path.stat().st_size < self._max_bytes:
                return
        except OSError:
            return
        backup = self._path.with_suffix(".jsonl.1")
        try:
            backup.unlink(missing_ok=True)
            self._path.rename(backup)
        except OSError as exc:
            print(f"[journal] не удалось повернуть журнал: {exc}")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def count_changes(before: str, after: str) -> int:
    """Сколько слов правка тронула.

    Считаем по словам, а не по символам: замена «заводилась» на «завелась» —
    одно вмешательство, а не шесть, и по словам это видно честнее.
    """
    if not after:
        return 0
    a, b = before.split(), after.split()
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )
