"""Правки, сделанные руками уже после вставки.

Диктовка проходит через две модели, и ошибиться может каждая: Whisper —
расслышав, редактор — исправив. Кто именно ошибся, журнал не знает, потому что
не знает, как было сказано на самом деле. Знает человек — и правит текст прямо
там, куда он вставился.

Отсюда способ: выделить исправленное предложение и нажать клавишу. Приложение
само копирует выделенное, ищет, из какой диктовки оно выросло, и дописывает в
журнал одни различия. Плашку раскрывать не надо, фокус из окна не уходит, а на
счастливом пути — когда править нечего — не нужно и нажатия.

Выделенное, которое ни на что не похоже, не пишется никуда: в буфер обмена
попадает всякое, и журналу оно ни к чему.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from difflib import SequenceMatcher

from PySide6.QtCore import QObject, Signal

from core.journal import Correction, Journal, count_changes, diff_words, word_key
from core.paster import ClipboardError, active_app, grab_selection

#: Сколько последних диктовок просматриваем. Ошибку замечают не сразу, но и не
#: через сотню фраз, а перебор по всему журналу стоил бы чтения мегабайтов.
_LOOKBACK = 20

#: Ниже этой доли совпавших слов считаем, что выделено не из диктовки. Обычная
#: правка — одно-два слова во фразе, это 0.85 и выше; всё, что близко к порогу,
#: скорее чужой текст, и записать его было бы хуже, чем не записать ничего.
_FLOOR = 0.6


@dataclass
class Match:
    """Диктовка, из которой выросло выделенное, и её кусок под ним."""

    row: dict
    span: str
    score: float


def find(selection: str, rows: list[dict]) -> Match | None:
    """Ищет диктовку, к которой относится выделенное.

    Выделяют обычно не всю диктовку, а одно предложение из неё, поэтому меряем
    не похожесть целиком — у куска она низкая по определению, — а долю
    выделенных слов, нашедшихся в диктовке подряд.
    """
    keys = [word_key(word) for word in selection.split()]
    if not keys:
        return None

    best: Match | None = None
    for row in rows:
        final = (row.get("final") or "").split()
        if not final:
            continue
        matcher = SequenceMatcher(
            None, [word_key(word) for word in final], keys, autojunk=False
        )
        blocks = [block for block in matcher.get_matching_blocks() if block.size]
        if not blocks:
            continue
        score = sum(block.size for block in blocks) / len(keys)
        # Строго больше: диктовки идут от свежих к старым, и при равном счёте
        # правка почти наверняка относится к последней из них.
        if score < _FLOOR or (best is not None and score <= best.score):
            continue
        start, stop = blocks[0].a, blocks[-1].a + blocks[-1].size
        best = Match(row=row, span=" ".join(final[start:stop]), score=round(score, 3))
    return best


def describe(correction: Correction, limit: int = 2) -> str:
    """Что человек поправил — строкой для плашки.

    Двух пар хватает: в плашку помещается около шестидесяти знаков, третья
    всё равно ушла бы в многоточие вместе с «и ещё», а полная правка лежит
    в журнале.
    """
    parts = []
    for change in correction.changes[:limit]:
        if change.was and change.now:
            parts.append(f"{change.was} → {change.now}")
        elif change.was:
            parts.append(f"{change.was} →")
        else:
            parts.append(f"→ {change.now}")
    if len(correction.changes) > limit:
        parts.append(f"и ещё {len(correction.changes) - limit}")
    return " · ".join(parts)


class Corrector(QObject):
    """Снимает выделение по горячей клавише и дописывает правку в журнал."""

    noted = Signal(object)
    """Правка записана; в аргументе — сама journal.Correction."""

    missed = Signal(str)
    """Записывать нечего или не к чему; в аргументе — что сказать человеку."""

    def __init__(self, journal: Journal) -> None:
        super().__init__()
        self._journal = journal

    def capture(self, hotkey: str = "") -> None:
        """Разбирает выделение в своём потоке.

        Ожидание буфера обмена — это до полусекунды, и в потоке интерфейса оно
        подвесило бы анимацию ровно тогда, когда плашка должна отвечать.
        """
        threading.Thread(
            target=self._capture, args=(hotkey,), name="correction", daemon=True
        ).start()

    def _capture(self, hotkey: str) -> None:
        try:
            selection = grab_selection(hotkey).strip()
        except ClipboardError as exc:
            self.missed.emit(str(exc))
            return
        if not selection:
            self.missed.emit("выделите исправленный текст и нажмите ещё раз")
            return

        found = find(selection, self._journal.recent(_LOOKBACK))
        if found is None:
            self.missed.emit("не нашёл, из какой это диктовки — выделите предложение целиком")
            return

        changes = diff_words(found.span, selection)
        if not changes:
            self.missed.emit("здесь всё как продиктовано")
            return

        correction = Correction(
            of=found.row.get("id", ""),
            was=found.span,
            fixed=selection,
            changes=changes,
            changed_words=count_changes(changes),
            match=found.score,
            app=active_app(),
            ago_s=_ago(found.row.get("at", "")),
        )
        self._journal.write(correction)
        print(f"[corrections] {describe(correction)}")
        self.noted.emit(correction)


def _ago(at: str) -> float:
    """Сколько прошло с диктовки. Время в журнале местное, как его записали."""
    try:
        stamp = time.mktime(time.strptime(at, "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return 0.0
    return round(max(0.0, time.time() - stamp), 1)
