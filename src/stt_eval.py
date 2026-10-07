"""Замер подсказки Whisper на своих записях: python src/stt_eval.py <команда>

    cases           собрать записи диктовок и вопросов в refs.txt с черновиками эталонов
    listen [метка]  прослушать записи с черновиком; метка — термины, коротко или паузы
    run             распознать записи с эталоном во всех вариантах подсказки
    report          метрики вариантов против базы без подсказки

Гипотеза: подсказка из своего словаря — английских терминов, которые человек
правда говорит, — поможет Whisper их расслышать. Цена тоже известна: подсказку
Whisper принимает за сказанное до записи и на тишине договаривает — 6.10.2026
так вставился хвост глоссария чертёжника. Поэтому мерим обе стороны: сколько
терминов стало верно, что подсказка сделала с остальными словами и сколько
слов словаря появилось там, где их не говорили.

Варианты: «база» без подсказки — дважды, потому что облако и при temperature 0
может ответить на ту же запись иначе, и разница меньше этого разброса — не
результат; «список» — словарь через запятую; и каждый файл из prompts/ — своя
подсказка, например тот же словарь фразами.

Эталон пишет человек, прослушав запись, а черновик — сырой текст Whisper, то
есть почти ответ базы. Ошибка, пропущенная в черновике, играет за базу: если
словарь всё равно выигрывает, выигрыш не от черновика.

Всё лежит в каталоге stt_eval рядом с журналом: записи и тексты личные, в
репозиторий отсюда не попадает ничего. Распознаёт тот же CloudClient, что и
приложение, но без запасного сервера: OpenRouter подсказку не принимает, и
замер ушёл бы тихо мерить «без подсказки» на платном тарифе.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import re
import sys
import time
import wave
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from config import Config, app_data_dir
from core.cloud import CloudClient, CloudUnavailable

DATA = app_data_dir()
ROOT = DATA / "stt_eval"
REFS = ROOT / "refs.txt"
VOCAB = ROOT / "vocab.txt"
PROMPTS = ROOT / "prompts"
RUNS = ROOT / "runs"

#: Предел подсказки Whisper. Длиннее облако отбивает запрос целиком, а клиент
#: после этого перестаёт слать подсказки вовсе — до перезапуска.
PROMPT_TOKENS = 224

BASE = ("база", "база·2")

#: Границы меток — по журналу на 7.10.2026: до 5 слов или меньше 4 с — около
#: 5% диктовок, тишина от половины записи — верхняя четверть.
_SHORT_WORDS, _SHORT_S, _PAUSES = 5, 4.0, 0.5

_LATIN = re.compile(r"[A-Za-z]{2,}")
_FIELD = re.compile(r"^(звук|метки|сырой|черновик|эталон):\s?(.*)$")

_REFS_HEAD = """\
# Эталоны для замера подсказки Whisper. Блок — одна запись.
# «черновик:» — сырой текст Whisper, в замер не идёт. Прослушай запись
# (python src/stt_eval.py listen), исправь текст так, как было сказано, и
# замени «черновик:» на «эталон:». Слова-паразиты оставляй: эталон — это речь,
# а не правка. Термины из vocab.txt пиши как в словаре: GPT-OSS, а не «гпт осс».
"""

_VOCAB_HEAD = """\
# Словарь для подсказки Whisper: термины, которые должны писаться латиницей.
# Строка — термин, как его надо писать. После «=» через запятую — как его ещё
# пишет Whisper, когда расслышал верно, но кириллицей: это засчитывается как
# «узнал», но не как «как в словаре». «*» в конце — любое окончание: «грок*»
# найдёт и «гроке», «Groq*» — и «Groqe». В подсказку «*» не идёт. Порядок
# строк — порядок терминов в подсказке «список».
"""


# ---------- словарь и сравнение текстов ----------


def normalize(text: str) -> list[str]:
    """Слова для сравнения: без регистра, знаков и дефисов, ё как е.

    Расставить знаки — забота правки, а не Whisper, и «GPT-OSS» с «gpt oss» —
    одно и то же сказанное.
    """
    text = text.lower().replace("ё", "е")
    return re.sub(r"[^\w]+|_", " ", text).split()


@dataclass
class Term:
    name: str
    spellings: list[tuple[str, ...]]
    """Все написания словами: первое — как в словаре, дальше — кириллица."""


def load_vocab() -> list[Term]:
    if not VOCAB.exists():
        return []
    def spelling(text: str) -> tuple[str, ...]:
        return tuple(normalize(text)) + (("*",) if text.strip().endswith("*") else ())

    terms = []
    for line in VOCAB.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, rest = line.partition("=")
        spellings = [spelling(name)] + [spelling(alt) for alt in rest.split(",") if alt.strip()]
        terms.append(Term(name.strip().rstrip("*"), [s for s in spellings if s and s != ("*",)]))
    return terms


def _matches(words: list[str], at: int, spelling: tuple[str, ...]) -> int:
    """Сколько слов с позиции at занимает написание; 0 — не совпало."""
    stem = spelling[-1] == "*"
    parts = spelling[:-1] if stem else spelling
    if at + len(parts) > len(words):
        return 0
    for offset, part in enumerate(parts):
        word = words[at + offset]
        last = offset == len(parts) - 1
        if not (word.startswith(part) if stem and last else word == part):
            return 0
    return len(parts)


def find_terms(words: list[str], vocab: list[Term], canonical: bool = False) -> list[tuple[int, int, int]]:
    """Вхождения терминов: (номер термина, начало, конец) без перекрытий.

    Длинные написания — первыми: иначе в «пай торч» нашёлся бы ещё и «торч».
    canonical — только как в словаре, без кириллических написаний.
    """
    options = [
        (index, spelling)
        for index, term in enumerate(vocab)
        for spelling in (term.spellings[:1] if canonical else term.spellings)
    ]
    options.sort(key=lambda item: -len(item[1]))
    found, taken = [], [False] * len(words)
    for at in range(len(words)):
        if taken[at]:
            continue
        for index, spelling in options:
            size = _matches(words, at, spelling)
            if size and not any(taken[at:at + size]):
                found.append((index, at, at + size))
                for k in range(at, at + size):
                    taken[k] = True
                break
    return found


def align(ref: list[str], hyp: list[str]) -> list[tuple[str, int, int]]:
    """Выравнивание по Левенштейну: (вид, позиция в эталоне, в гипотезе).

    Вид: «=» совпало, «~» замена, «-» пропуск, «+» вставка. Позиция вставки в
    эталоне — слово, перед которым она стоит.
    """
    n, m = len(ref), len(hyp)
    cost = np.zeros((n + 1, m + 1), dtype=np.int32)
    cost[:, 0] = np.arange(n + 1)
    cost[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i, j] = min(
                cost[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]),
                cost[i - 1, j] + 1,
                cost[i, j - 1] + 1,
            )
    ops, i, j = [], n, m
    while i or j:
        if i and j and cost[i, j] == cost[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(("=" if ref[i - 1] == hyp[j - 1] else "~", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and cost[i, j] == cost[i - 1, j] + 1:
            ops.append(("-", i - 1, j))
            i -= 1
        else:
            ops.append(("+", i, j - 1))
            j -= 1
    return ops[::-1]


@dataclass
class Score:
    """Одна запись в одном варианте."""

    ref_terms: dict[int, int] = field(default_factory=dict)
    heard: dict[int, int] = field(default_factory=dict)
    """Сколько вхождений термина распознано любым написанием (не больше, чем в эталоне)."""

    exact: dict[int, int] = field(default_factory=dict)
    """…и сколько — как в словаре."""

    inserted: dict[int, int] = field(default_factory=dict)
    """Термины сверх эталона: их не говорили — значит, подсказали."""

    errors: int = 0
    words: int = 0
    other_errors: int = 0
    """Ошибки в словах, которые не термины: не испортила ли подсказка соседей."""

    other_words: int = 0


def score(ref_text: str, hyp_text: str, vocab: list[Term]) -> Score:
    ref, hyp = normalize(ref_text), normalize(hyp_text)
    result = Score(errors=0, words=len(ref))
    in_term = [False] * len(ref)
    for index, start, end in find_terms(ref, vocab):
        result.ref_terms[index] = result.ref_terms.get(index, 0) + 1
        for k in range(start, end):
            in_term[k] = True
    got: dict[int, int] = {}
    for index, _, _ in find_terms(hyp, vocab):
        got[index] = got.get(index, 0) + 1
    got_exact: dict[int, int] = {}
    for index, _, _ in find_terms(hyp, vocab, canonical=True):
        got_exact[index] = got_exact.get(index, 0) + 1
    for index in set(result.ref_terms) | set(got):
        said = result.ref_terms.get(index, 0)
        result.heard[index] = min(said, got.get(index, 0))
        result.exact[index] = min(said, got_exact.get(index, 0))
        result.inserted[index] = max(0, got.get(index, 0) - said)

    # Ошибку у границы термина записываем на термин: вставка «ос» рядом с
    # «GPT-OSS» — это термин, распознанный в два слова, а не порча соседей.
    near = lambda i: (i < len(ref) and in_term[i]) or (i > 0 and in_term[i - 1])
    result.other_words = in_term.count(False)
    for kind, i, _ in align(ref, hyp):
        if kind == "=":
            continue
        result.errors += 1
        if (kind == "+" and not near(i)) or (kind != "+" and not in_term[i]):
            result.other_errors += 1
    return result


def mcnemar(b: int, c: int) -> float:
    """Точный двусторонний тест Макнемара: p для b против c разошедшихся пар.

    Пара — одно вхождение термина в двух вариантах. Совпавшие пары о разнице
    ничего не говорят; вопрос в том, могли ли разошедшиеся лечь так случайно,
    как монетка. Вхождения в одной записи не вполне независимы, так что p —
    ориентир, а не приговор.
    """
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


# ---------- набор записей ----------


@dataclass
class Case:
    id: str
    header: str
    audio: str = ""
    tags: list[str] = field(default_factory=list)
    raw: str = ""
    text: str = ""
    confirmed: bool = False

    @property
    def path(self) -> Path:
        return DATA / self.audio


def read_refs() -> list[Case]:
    if not REFS.exists():
        return []
    cases: list[Case] = []
    key = ""
    for line in REFS.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            header = line[3:].strip()
            cases.append(Case(id=header.split()[0], header=header))
            key = ""
            continue
        if not cases or not line.strip() or line.startswith("#"):
            continue
        case = cases[-1]
        match = _FIELD.match(line.strip())
        if match is None:
            # Длинный эталон разрешаем переносить: продолжение без ключа.
            if key in ("черновик", "эталон"):
                case.text += " " + line.strip()
            continue
        key, value = match.groups()
        if key == "звук":
            case.audio = value.strip()
        elif key == "метки":
            case.tags = [tag.strip() for tag in value.split(",") if tag.strip()]
        elif key == "сырой":
            case.raw = value.strip()
        else:
            case.text, case.confirmed = value.strip(), key == "эталон"
    return cases


def journal_rows() -> list[dict]:
    rows = []
    for path in (DATA / "dictations.jsonl.1", DATA / "dictations.jsonl"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def tags_of(row: dict, raw: str, vocab: list[Term]) -> list[str]:
    tags = []
    words = normalize(raw)
    if _LATIN.search(raw) or _LATIN.search(row.get("final", "")) or find_terms(words, vocab):
        tags.append("термины")
    if len(words) <= _SHORT_WORDS or row.get("audio_s", 0) < _SHORT_S:
        tags.append("коротко")
    if row.get("silence", 0) >= _PAUSES:
        tags.append("паузы")
    return tags


def cmd_cases() -> int:
    """Дописывает в refs.txt записи, которых там ещё нет. Свои правки не трогает."""
    ROOT.mkdir(parents=True, exist_ok=True)
    if not VOCAB.exists():
        VOCAB.write_text(_VOCAB_HEAD, encoding="utf-8")
        print(f"Создал пустой словарь {VOCAB} — заполни его до прогона.")
    vocab = load_vocab()
    known = {case.id for case in read_refs()}
    blocks = []
    for row in journal_rows():
        name = row.get("audio_file")
        if not name or row.get("id") in known:
            continue
        folder = "asks" if row.get("kind") == "ask" else "dictations"
        if not (DATA / folder / name).exists():
            continue  # запись уже ушла за потолок каталога
        raw = row.get("question", "") if row.get("kind") == "ask" else row.get("raw", "")
        at = time.strftime("%d.%m %H:%M", time.strptime(row["at"], "%Y-%m-%dT%H:%M:%S"))
        head = f"## {row['id']} · {at} · {row.get('audio_s', 0):.1f} с · {row.get('app') or '—'}"
        if row.get("kind") == "ask":
            head += " · вопрос"
        if row.get("stt_prompt"):
            head += " · была подсказка"
        blocks.append("\n".join([
            head,
            f"звук: {folder}/{name}",
            f"метки: {', '.join(tags_of(row, raw, vocab))}",
            f"сырой: {raw}",
            f"черновик: {raw}",
        ]))
        known.add(row.get("id"))
    if blocks:
        with REFS.open("a", encoding="utf-8") as handle:
            if handle.tell() == 0:
                handle.write(_REFS_HEAD)
            handle.write("\n" + "\n\n".join(blocks) + "\n")
    cases = read_refs()
    done = sum(case.confirmed for case in cases)
    print(f"{REFS}: записей {len(cases)}, новых {len(blocks)}, с эталоном {done}")
    if not cases:
        print("Записей со звуком нет: включи audio.keep_dictations в config.json и подиктуй.")
    return 0


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
    return pcm.astype(np.float32) / 32767, rate


def cmd_listen(tag: str) -> int:
    """Слушать запись и тут же править её черновик в refs.txt."""
    import sounddevice as sd

    cases = [c for c in read_refs() if not c.confirmed and c.path.exists() and (not tag or tag in c.tags)]
    if not cases:
        print("Слушать нечего: черновиков" + (f" с меткой «{tag}»" if tag else "") + " нет.")
        return 0
    print(f"{len(cases)} черновиков. Правь их в {REFS}: черновик → эталон.")
    print("Enter — дальше, п — ещё раз, в — выйти.\n")
    if sys.platform == "win32":
        os.startfile(REFS)
    for number, case in enumerate(cases, 1):
        print(f"[{number}/{len(cases)}] {case.header} · {', '.join(case.tags)}")
        print(f"  {case.raw}")
        audio, rate = read_wav(case.path)
        while True:
            sd.play(audio, rate)
            answer = input("  > ").strip().lower()
            sd.stop()
            if answer in ("п", "r"):
                continue
            if answer in ("в", "q"):
                return 0
            break
    return 0


# ---------- прогон ----------


def load_variants(vocab: list[Term]) -> dict[str, str]:
    variants = {name: "" for name in BASE}
    if vocab:
        variants["список"] = ", ".join(term.name for term in vocab)
    for path in sorted(PROMPTS.glob("*.txt")) if PROMPTS.exists() else []:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
        variants[path.stem] = " ".join(" ".join(lines).split())
    return variants


@lru_cache(maxsize=1)
def _tokenizer(model: str):
    """Токенизатор Whisper из кэша faster-whisper; None — его нет (лёгкая сборка)."""
    try:
        from faster_whisper.utils import download_model
        from tokenizers import Tokenizer

        return Tokenizer.from_file(str(Path(download_model(model, local_files_only=True)) / "tokenizer.json"))
    except Exception:
        return None


def prompt_tokens(prompt: str, model: str) -> int | None:
    tokenizer = _tokenizer(model)
    if tokenizer is None or not prompt:
        return None if prompt else 0
    # faster-whisper кодирует подсказку с пробелом впереди — так и считаем.
    return len(tokenizer.encode(" " + prompt.strip(), add_special_tokens=False).ids)


#: «…сброс через 7 с» в тексте отказа по лимиту.
_RESET = re.compile(r"сброс через (\d+)")

#: Отказы, которые проходят сами: лимит, перегрузка, тишина в ответ.
_PASSING = ("лимит", "вовремя", "ответило 5")


def transcribe_patiently(client: CloudClient, audio: np.ndarray, rate: int, language: str, prompt: str) -> dict:
    """Одна запись с ожиданием отказов, которые проходят сами.

    Суточный лимит ждать минутами бесполезно: если до сброса дольше пары
    минут, прогон останавливается и докачает недостающее в следующий запуск.
    """
    for attempt in range(5):
        started = time.monotonic()
        try:
            text = client.transcribe(audio, rate, language, prompt)
        except CloudUnavailable as exc:
            message = str(exc)
            match = _RESET.search(message)
            wait = int(match.group(1)) + 2 if match else 15 * (attempt + 1)
            if not any(mark in message for mark in _PASSING) or attempt == 4 or wait > 120:
                return {"error": message, "stop": wait > 120}
            print(f"    {message}; жду {wait} с")
            time.sleep(wait)
            continue
        if prompt and not client.sends_prompt:
            return {"error": "облако не приняло подсказку", "stop": True}
        return {"text": text, "took_s": round(time.monotonic() - started, 2), "stt": client.whisper_model}
    return {"error": "не дождался лимита"}


def collect(variants: dict[str, str]) -> dict[tuple[str, str], dict]:
    """Распознанное по нынешним вариантам: (запись, вариант) -> строка прогона.

    Строка с другой подсказкой — от прежней редакции словаря — не считается:
    правка словаря должна перемерить вариант, а не смешаться со старым.
    """
    rows: dict[tuple[str, str], dict] = {}
    for run in sorted(RUNS.glob("*.jsonl")) if RUNS.exists() else []:
        for line in run.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if variants.get(row["variant"]) != row["prompt"] or "text" not in row:
                continue
            rows[(row["case"], row["variant"])] = row
    return rows


def cmd_run() -> int:
    cfg = Config.load()
    # Без запасного сервера: см. в начале файла.
    cloud_cfg = dataclasses.replace(cfg.cloud, reserve=dataclasses.replace(cfg.cloud.reserve, api_key=""))
    client = CloudClient(cloud_cfg, cfg.llm)
    if not client.configured:
        print("Нет ключа облака (cloud.api_key): распознавать нечем.")
        return 1
    vocab = load_vocab()
    variants = load_variants(vocab)
    for name, prompt in list(variants.items()):
        tokens = prompt_tokens(prompt, cfg.whisper.model)
        if tokens is not None and tokens > PROMPT_TOKENS:
            print(f"Пропускаю «{name}»: {tokens} токенов при пределе {PROMPT_TOKENS}")
            del variants[name]
        elif prompt:
            print(f"«{name}»: " + (f"{tokens} токенов" if tokens is not None else "длину не проверить — нет токенизатора"))

    cases = [case for case in read_refs() if case.confirmed and case.path.exists()]
    if not cases:
        print("Записей с эталоном нет: python src/stt_eval.py cases, потом listen.")
        return 1
    done = collect(variants)
    todo = [(case, name) for case in cases for name in variants if (case.id, name) not in done]
    if not todo:
        print("Всё уже распознано: python src/stt_eval.py report")
        return 0

    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / (time.strftime("%Y%m%d-%H%M") + ".jsonl")
    print(f"{len(todo)} распознаваний: {len(cases)} записей × {len(variants)} вариантов, без готовых → {out.name}")
    started = time.monotonic()
    with out.open("a", encoding="utf-8") as handle:
        # Варианты по очереди внутри записи, а не весь набор подряд: прерванный
        # прогон оставляет готовые пары, а не один вариант без другого.
        for number, (case, name) in enumerate(todo, 1):
            audio, rate = read_wav(case.path)
            row = {"case": case.id, "variant": name, "prompt": variants[name]}
            row.update(transcribe_patiently(client, audio, rate, cfg.whisper.language, variants[name]))
            stop = row.pop("stop", False)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            print(f"[{number}/{len(todo)}] {case.id} · {name}: " + (f"{row['took_s']:.1f} с" if "text" in row else row["error"]))
            if stop:
                print("Останавливаю прогон: дальше будет то же самое.")
                break
    print(f"Прогон занял {time.monotonic() - started:.0f} с. Отчёт: python src/stt_eval.py report")
    return 0


# ---------- отчёт ----------


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "—"


def cmd_report() -> int:
    cfg = Config.load()
    vocab = load_vocab()
    variants = load_variants(vocab)
    rows = collect(variants)
    # Только записи, распознанные во всех вариантах: сравнение парное, на
    # одном и том же звуке, иначе разница — это разница наборов.
    cases = [
        case for case in read_refs()
        if case.confirmed and all((case.id, name) in rows for name in variants)
    ]
    if not cases:
        print("Нет записей, распознанных во всех вариантах: python src/stt_eval.py run")
        return 1

    scores = {name: {case.id: score(case.text, rows[(case.id, name)]["text"], vocab) for case in cases} for name in variants}
    tagged = lambda tag: [case for case in cases if tag in case.tags]
    no_terms = [case for case in cases if not scores[BASE[0]][case.id].ref_terms]
    said = sum(sum(s.ref_terms.values()) for s in scores[BASE[0]].values())

    out = [
        f"Замер подсказки Whisper · {time.strftime('%d.%m.%Y %H:%M')} · {rows[(cases[0].id, BASE[0])].get('stt', '')}",
        f"Записей: {len(cases)} (без терминов {len(no_terms)}, коротких {len(tagged('коротко'))}, "
        f"с паузами {len(tagged('паузы'))}); вхождений терминов в эталонах: {said}",
        "",
        f"{'вариант':<12}{'токены':>7}{'узнал':>9}{'как в словаре':>15}{'WER':>8}{'WER не терм.':>14}"
        f"{'вставки: все / без терм. / коротко / паузы':>45}",
    ]
    for name, prompt in variants.items():
        per = scores[name]
        heard = sum(sum(s.heard.values()) for s in per.values())
        exact = sum(sum(s.exact.values()) for s in per.values())
        errors, words = sum(s.errors for s in per.values()), sum(s.words for s in per.values())
        other = sum(s.other_errors for s in per.values())
        other_words = sum(s.other_words for s in per.values())
        inserted = " / ".join(
            str(sum(sum(per[c.id].inserted.values()) for c in group))
            for group in (cases, no_terms, tagged("коротко"), tagged("паузы"))
        )
        tokens = prompt_tokens(prompt, cfg.whisper.model)
        out.append(
            f"{name:<12}{tokens if tokens is not None else '?':>7}{_pct(heard, said):>9}{_pct(exact, said):>15}"
            f"{_pct(errors, words):>8}{_pct(other, other_words):>14}{inserted:>45}"
        )

    first, second = BASE
    differ = sum(normalize(rows[(c.id, first)]["text"]) != normalize(rows[(c.id, second)]["text"]) for c in cases)
    drift = sum(len([o for o in align(normalize(rows[(c.id, first)]["text"]), normalize(rows[(c.id, second)]["text"])) if o[0] != "="]) for c in cases)
    base_words = sum(len(normalize(rows[(c.id, first)]["text"])) for c in cases)
    out += [
        "",
        f"Разброс облака: «{first}» и «{second}» разошлись в {differ} записях из {len(cases)}, "
        f"{_pct(drift, base_words)} слов. Разница с базой меньше этого — шум.",
        "",
        "Против базы по вхождениям терминов («узнал»), точный тест Макнемара:",
    ]
    for name in variants:
        if name == first:
            continue
        fixed = broken = 0
        for case in cases:
            base, other = scores[first][case.id], scores[name][case.id]
            for index in base.ref_terms:
                delta = other.heard.get(index, 0) - base.heard.get(index, 0)
                fixed += max(0, delta)
                broken += max(0, -delta)
        out.append(f"  {name:<12} исправил {fixed}, сломал {broken}, p = {mcnemar(fixed, broken):.3f}")

    out += ["", "По терминам — сказано / узнал в каждом варианте:"]
    names = list(variants)
    out.append(f"  {'термин':<18}{'сказано':>8}" + "".join(f"{name:>12}" for name in names))
    for index, term in enumerate(vocab):
        total = sum(scores[first][c.id].ref_terms.get(index, 0) for c in cases)
        cells = []
        for n in names:
            heard = sum(scores[n][c.id].heard.get(index, 0) for c in cases)
            extra = sum(scores[n][c.id].inserted.get(index, 0) for c in cases)
            cells.append((f"{heard}+{extra}" if extra else str(heard)).rjust(12))
        if total or any("+" in cell for cell in cells):
            out.append(f"  {term.name:<18}{total:>8}" + "".join(cells))
    out.append("  «+N» — вставлен там, где его не говорили.")

    out += ["", "Вставки — термины, которых нет в эталоне:"]
    for name in names:
        for case in cases:
            extra = [vocab[i].name for i, k in scores[name][case.id].inserted.items() if k]
            if extra:
                out.append(f"  {name} · {case.id} · {', '.join(extra)}: {rows[(case.id, name)]['text'][:160]}")

    report = "\n".join(out)
    print(report)
    path = ROOT / f"report-{time.strftime('%Y%m%d-%H%M')}.txt"
    path.write_text(report + "\n", encoding="utf-8")
    print(f"\nОтчёт сохранён: {path}")
    return 0


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command == "cases":
        return cmd_cases()
    if command == "listen":
        return cmd_listen(argv[2] if len(argv) > 2 else "")
    if command == "run":
        return cmd_run()
    if command == "report":
        return cmd_report()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
