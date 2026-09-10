"""Журнал диктовок: что сказал Whisper, что из этого сделала модель, сколько это стоило.

История в трее держит десять последних записей и только итоговый текст. По ней
нельзя ответить ни на один вопрос, который возникает при настройке: что модель
изменила, сколько ждали, как часто правка вообще что-то меняет. Журнал пишет всё,
что знает конвейер, — по строке JSON на диктовку.

Формат построчный намеренно: дописывается без перечитывания файла, читается
частями и переживает обрыв записи — битой окажется одна последняя строка, а не
весь журнал.

Эталона у нас нет, и правильность правки журнал не измеряет. Зато он измеряет
объём вмешательства: какие слова модель тронула и сколько их. На чистом входе
это число должно быть близко к нулю, и всплеск в нём — первый признак, что
модель начала пересказывать вместо чистки.

Файл лежит рядом с конфигом и содержит всё надиктованное открытым текстом.
Никуда не отправляется, но выключается в настройках: llm/journal -> false.
"""

from __future__ import annotations

import difflib
import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from config import APP_VERSION, app_data_dir


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def new_id() -> str:
    """Короткий ключ записи вида «0911-a3f7c1».

    Нужен, чтобы к диктовке можно было привязать правку, сделанную руками
    много позже. Дата в начале — чтобы ключ читался глазами при поиске по
    файлу; шести шестнадцатеричных цифр хватает, чтобы два ключа за один день
    не совпали.
    """
    return time.strftime("%m%d") + "-" + secrets.token_hex(3)


@dataclass
class Change:
    """Одно вмешательство: что стояло в исходном тексте и чем стало."""

    was: str
    now: str


@dataclass
class Attempt:
    """Одна попытка правки.

    Их бывает две: облако не ответило — правку доделывает Ollama. Раньше вторая
    попытка затирала первую вместе с её временем и ответом, и по журналу
    выходило, что откат не случился вовсе и обошёлся бесплатно.
    """

    model: str = ""
    took_s: float = 0.0
    output_tokens: int = 0
    gen_s: float = 0.0
    """Время именно генерации: по нему считается ток/с, не завися от очереди."""

    response: str = ""
    """Ответ модели до вычистки обёрток — по нему видно, что она приписывает."""

    text: str = ""
    accepted: bool | None = None
    """Прошёл ли ответ проверку на осмысленность. None — ответа не было."""

    error: str = ""
    """Чем попытка сорвалась, если сорвалась."""


@dataclass
class Record:
    """Одна диктовка от нажатия клавиши до вставки."""

    id: str = field(default_factory=new_id)
    """Ключ, по которому к диктовке цепляется правка, сделанная руками потом."""

    at: str = field(default_factory=now)
    version: str = APP_VERSION
    """Какая сборка сделала запись: без этого поля старые записи не отличить."""

    audio_s: float = 0.0
    hotkey: str = ""

    app: str = ""
    """Приложение, в которое ушёл текст. В разных окнах диктуют по-разному —
    в мессенджер разговорно, в редактор терминами, — и ошибается Whisper тоже
    по-разному. Заголовок окна не берём: в нём бывает и переписка, и пути."""

    rms: float = 0.0
    """Средняя громкость записи: тихая комната около 0.001, речь 0.02..0.15."""

    peak: float = 0.0
    clipped: float = 0.0
    """Доля отсчётов, упёршихся в потолок: больше нуля — микрофон перегружен."""

    silence: float = 0.0
    """Доля фразы, проведённая в тишине: на длинных паузах Whisper дорисовывает."""

    whisper_s: float = 0.0
    stt: str = ""
    """Кто распознавал: «large-v3-turbo · cuda» или облачная модель."""

    stt_error: str = ""
    """Облачный Whisper не ответил и распознавал местный — здесь причина."""

    raw: str = ""
    """Сырой текст Whisper — то, чего сейчас нигде не сохраняется."""

    style: str = ""
    """Стиль правки: careful, dry или пусто, если модель не звали."""

    skipped: str = ""
    """Почему пропустили правку: «выключена», «слишком коротко», «сырой режим»."""

    attempts: list[Attempt] = field(default_factory=list)
    """Все попытки правки по порядку — и сорвавшиеся тоже."""

    error: str = ""
    """Что оборвало диктовку до вставки. Сорвавшаяся правка сюда не попадает:
    текст всё равно вставился, а причина лежит в своей попытке."""

    cloud_quota: str = ""
    """Остатки лимитов облака после этой диктовки, если её правило облако."""

    final: str = ""
    """То, что реально ушло в активное окно."""

    changes: list[Change] = field(default_factory=list)
    """Что правка сделала со словами. Счётчика мало: по нему виден объём
    вмешательства, но не видно, что именно модель меняет из раза в раз."""

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


#: Знаки, которые снимаются со слова перед сравнением.
_MARKS = str.maketrans("", "", ".,!?…:;\"'«»()")


def _key(word: str) -> str:
    """По чему сравниваем слова.

    Расставить точки и заглавные — прямая обязанность модели по промпту, и
    считать это вмешательством нельзя: иначе каждая до последнего слова верная
    фраза выглядит переписанной, а «Надо» и «надо» не встают друг против друга
    и склеивают соседние правки в один нечитаемый кусок.
    """
    return word.translate(_MARKS).lower()


def diff_words(before: str, after: str) -> list[Change]:
    """Что правка сделала со словами: пары «было -> стало».

    Считаем по словам, а не по символам: замена «заводилась» на «завелась» —
    одно вмешательство, а не шесть, и по словам это видно честнее. Вставка и
    удаление записываются той же парой с пустой половиной.
    """
    if not after:
        return []
    a, b = before.split(), after.split()
    matcher = difflib.SequenceMatcher(
        None, [_key(word) for word in a], [_key(word) for word in b], autojunk=False
    )
    return [
        Change(was=" ".join(a[i1:i2]), now=" ".join(b[j1:j2]))
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


def count_changes(changes: list[Change]) -> int:
    """Сколько слов правка тронула: за замену считаем большую из двух сторон."""
    return sum(max(len(c.was.split()), len(c.now.split())) for c in changes)
