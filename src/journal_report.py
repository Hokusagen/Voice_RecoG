"""Сводка по журналу диктовок: python src/journal_report.py [журнал.jsonl]

Эталона у нас нет, поэтому отчёт не берётся судить, правильно ли модель
исправила фразу. Он отвечает на вопросы, на которые ответить можно: как часто
правка вообще что-то меняет, что именно она меняет из раза в раз, насколько
глубоко вмешивается и сколько за это приходится ждать. Диктовки с самым большим
вмешательством выведены отдельно — именно их стоит посмотреть глазами.

Читает и записи старых версий: у них попытка правки одна и лежит плоскими
полями, а звука и приложения нет вовсе. Такие записи просто не попадают в
разделы, для которых у них нет данных.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from config import app_data_dir

#: До скольких слов замену считаем «не расслышал», а не «переписал заново».
_SHORT = 3

#: Знаки по краям слова, которые не должны плодить строки в частотнике.
_EDGE = ".,!?…:;\"'«»()-–—"


def load(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                # Обрыв записи бьёт одну строку, а не весь журнал.
                print(f"  (строка {number} повреждена, пропускаю)")
    return rows


def attempts(row: dict) -> list[dict]:
    """Попытки правки по порядку.

    До 0.6.0 попытка была одна и лежала плоскими полями — причём вторая
    затирала первую. Развернуть её обратно в список нельзя, но привести к
    общему виду можно, и тогда весь отчёт считается по одному правилу.
    """
    if "attempts" in row:
        return row["attempts"]
    if not row.get("llm_model"):
        return []
    return [{
        "model": row["llm_model"],
        "took_s": row.get("llm_s", 0.0),
        "output_tokens": row.get("output_tokens", 0),
        "gen_s": row.get("gen_s", 0.0),
        "response": row.get("response", ""),
        "text": row.get("polished", ""),
        "accepted": row.get("accepted"),
        "error": row.get("error", ""),
    }]


def verdict(row: dict) -> bool | None:
    """Чем кончилась правка: последняя попытка и решает, что вставилось."""
    tries = attempts(row)
    return tries[-1].get("accepted") if tries else None


def block(title: str) -> None:
    print(f"\n{title}\n" + "─" * len(title))


def stat(name: str, values: list[float], unit: str = "с") -> None:
    if not values:
        print(f"  {name:32s} —")
        return
    print(
        f"  {name:32s} медиана {statistics.median(values):6.2f} {unit}"
        f"   среднее {statistics.mean(values):6.2f} {unit}"
        f"   максимум {max(values):6.2f} {unit}"
    )


def table(pairs: list[tuple[str, int]], limit: int = 10) -> None:
    for label, count in pairs[:limit]:
        print(f"    {count:3d} × {label}")


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else app_data_dir() / "dictations.jsonl"
    if not path.exists():
        print(f"журнала нет: {path}")
        return 1

    rows = load(path)
    if not rows:
        print("журнал пуст")
        return 1

    block(f"Журнал {path}")
    print(f"  записей: {len(rows)}   с {rows[0]['at']} по {rows[-1]['at']}")
    print(f"  размер файла: {path.stat().st_size / 1024:.0f} КБ "
          f"({path.stat().st_size / len(rows):.0f} байт на диктовку)")

    block("Задержка")
    stat("вся диктовка", [r["total_s"] for r in rows])
    stat("Whisper", [r["whisper_s"] for r in rows])
    polished = [r for r in rows if attempts(r)]
    stat("правка модели", [sum(a["took_s"] for a in attempts(r)) for r in polished])

    speeds = [
        a["output_tokens"] / a["gen_s"]
        for r in polished for a in attempts(r)
        if a.get("gen_s", 0) > 0.05
    ]
    stat("генерация", speeds, "ток/с")

    block("Правка")
    skipped = [r for r in rows if r.get("skipped")]
    print(f"  правка звалась: {len(polished)} из {len(rows)}")
    reasons: dict[str, int] = {}
    for r in skipped:
        reasons[r["skipped"]] = reasons.get(r["skipped"], 0) + 1
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"    пропущено «{reason}»: {count}")

    rejected = [r for r in polished if verdict(r) is False]
    if rejected:
        print(f"  ⚠ отклонено проверкой: {len(rejected)} — вставился сырой текст")
    failed = [r for r in polished if verdict(r) is None]
    if failed:
        print(f"  ⚠ сорвалось до ответа: {len(failed)} — модель не отозвалась")

    # Откат виден только с тех пор, как попытки пишутся списком: до этого
    # вторая затирала первую, и по журналу его как будто не было.
    retried = [r for r in polished if len(attempts(r)) > 1]
    if retried:
        wasted = sum(a["took_s"] for r in retried for a in attempts(r)[:-1])
        print(f"  откатов на запасную модель: {len(retried)}"
              f" — {wasted:.0f} с ушло на попытки, которые не пригодились")
        for reason, count in Counter(
            a.get("error", "") for r in retried for a in attempts(r)[:-1] if a.get("error")
        ).most_common(3):
            print(f"    из-за «{reason}»: {count}")

    # Дальше считаем только по применённым правкам: у сорвавшихся правок ноль
    # изменений не потому, что модель ничего не нашла, а потому что её не было.
    applied = [r for r in polished if verdict(r) is True]
    if not applied:
        return 0

    untouched = [r for r in applied if r.get("changed_words", 0) == 0]
    print(f"  правка применилась: {len(applied)}")
    print(f"  из них ничего не изменила: {len(untouched)}"
          + (f" — {sum(sum(a['took_s'] for a in attempts(r)) for r in untouched):.0f} с ожидания впустую"
             if untouched else ""))

    words = sum(r.get("raw_words", 0) for r in applied)
    touched = sum(r.get("changed_words", 0) for r in applied)
    if words:
        print(f"  глубина вмешательства: {touched} из {words} слов ({100 * touched / words:.1f}%)")

    _changes(applied)
    _strongest(applied)
    _apps(rows)
    _sound(rows)

    leaked = [
        r for r in applied
        for a in attempts(r)[-1:]
        if a.get("response") and a["response"].strip() != a.get("text")
    ]
    if leaked:
        block("Ответы, которые пришлось чистить от обёрток")
        print(f"  таких записей: {len(leaked)} — модель приписывает разметку к ответу")
        for r in leaked[:3]:
            print(f"    {r['at']}: {attempts(r)[-1]['response'][:120]!r}")

    return 0


def _changes(applied: list[dict]) -> None:
    """Что модель правит из раза в раз.

    Счётчик изменений говорит, сколько слов тронуто; частотник — какие именно.
    Он и отвечает на вопрос, ради которого журнал заводился: одно и то же слово
    в этом списке значит, что Whisper его стабильно не слышит.

    Длинные куски отсюда выкинуты: переписанное целиком предложение — это не
    неуслышанное слово, а другая беда, и её показывает соседний раздел.
    """
    dropped: Counter[str] = Counter()
    replaced: Counter[str] = Counter()
    for row in applied:
        for change in row.get("changes") or []:
            was, now = change.get("was", "").strip(), change.get("now", "").strip()
            if len(was.split()) > _SHORT or len(now.split()) > _SHORT:
                continue
            # «ГОСТу» и «ГОСТу.» — одна и та же замена: точку модель ставит по
            # промпту, и разводить их по двум строкам частотника незачем.
            was, now = was.strip(_EDGE), now.strip(_EDGE)
            if was and not now:
                dropped[was.lower()] += 1
            elif was and now:
                replaced[f"{was} → {now}"] += 1

    if not dropped and not replaced:
        return
    block("Что модель меняет чаще всего")
    if dropped:
        print("  выбрасывает:")
        table(dropped.most_common())
    if replaced:
        print("  заменяет:")
        table(replaced.most_common())


def _strongest(applied: list[dict]) -> None:
    block("Самые сильные вмешательства")
    ranked = sorted(
        (r for r in applied if r.get("raw_words") and r.get("changed_words")),
        key=lambda r: r["changed_words"] / r["raw_words"],
        reverse=True,
    )
    if not ranked:
        print("  модель пока ничего не меняла")
    for r in ranked[:5]:
        share = 100 * r["changed_words"] / r["raw_words"]
        took = sum(a["took_s"] for a in attempts(r))
        print(f"\n  {r['at']}  тронуто {r['changed_words']}/{r['raw_words']} слов ({share:.0f}%)"
              f"   {took:.1f} с")
        print(f"    было : {r['raw'][:160]}")
        print(f"    стало: {r['final'][:160]}")


def _apps(rows: list[dict]) -> None:
    """Куда уходил текст. В разных окнах диктуют по-разному — и ошибаются тоже."""
    known = [r for r in rows if r.get("app")]
    if not known:
        return
    block("Куда вставляли")
    by_app: dict[str, list[dict]] = {}
    for row in known:
        by_app.setdefault(row["app"], []).append(row)
    for app, items in sorted(by_app.items(), key=lambda kv: -len(kv[1])):
        words = sum(r.get("raw_words", 0) for r in items)
        touched = sum(r.get("changed_words", 0) for r in items)
        share = f"{100 * touched / words:4.1f}%" if words else "    —"
        print(f"  {app:28s} {len(items):3d} диктовок   правка тронула {share} слов")


def _sound(rows: list[dict]) -> None:
    """Плохое распознавание бывает и от плохой записи — здесь видно, от какой."""
    known = [r for r in rows if r.get("rms")]
    if not known:
        return
    block("Звук")
    levels = [r["rms"] for r in known]
    print(f"  громкость: медиана {statistics.median(levels):.4f}"
          f"   тише всех {min(levels):.4f}   громче всех {max(levels):.4f}")

    loud = [r for r in known if r.get("clipped", 0) > 0.001]
    if loud:
        print(f"  ⚠ вход перегружен: {len(loud)} — микрофон бьёт в потолок")
    quiet = [r for r in known if r.get("rms", 1) < 0.01]
    if quiet:
        print(f"  ⚠ очень тихо: {len(quiet)} — говорили в сторону от микрофона")

    pauses = [r.get("silence", 0.0) for r in known]
    print(f"  доля тишины: медиана {100 * statistics.median(pauses):.0f}%"
          f"   максимум {100 * max(pauses):.0f}%")
    empty = [r for r in known if not r.get("raw")]
    if empty:
        share = statistics.median([r.get("silence", 0.0) for r in empty])
        print(f"  ничего не разобрано: {len(empty)}   медиана тишины в них {100 * share:.0f}%")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
