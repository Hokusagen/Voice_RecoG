"""Сводка по журналу диктовок: python src/journal_report.py [журнал.jsonl]

Эталона у нас нет, поэтому отчёт не берётся судить, правильно ли модель
исправила фразу. Он отвечает на вопросы, на которые ответить можно: как часто
правка вообще что-то меняет, насколько глубоко вмешивается и сколько за это
приходится ждать. Диктовки с самым большим вмешательством выведены отдельно —
именно их стоит посмотреть глазами.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from config import app_data_dir


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
    polished = [r for r in rows if r.get("llm_model")]
    stat("правка модели", [r["llm_s"] for r in polished])

    speeds = [r["output_tokens"] / r["gen_s"] for r in polished if r.get("gen_s", 0) > 0.05]
    stat("генерация", speeds, "ток/с")

    block("Правка")
    skipped = [r for r in rows if r.get("skipped")]
    print(f"  правка звалась: {len(polished)} из {len(rows)}")
    reasons: dict[str, int] = {}
    for r in skipped:
        reasons[r["skipped"]] = reasons.get(r["skipped"], 0) + 1
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"    пропущено «{reason}»: {count}")

    rejected = [r for r in polished if r.get("accepted") is False]
    if rejected:
        print(f"  ⚠ отклонено проверкой: {len(rejected)} — вставился сырой текст")
    failed = [r for r in polished if r.get("accepted") is None]
    if failed:
        print(f"  ⚠ сорвалось до ответа: {len(failed)} — Ollama не отозвалась")

    # Дальше считаем только по применённым правкам: у сорвавшихся правок ноль
    # изменений не потому, что модель ничего не нашла, а потому что её не было.
    applied = [r for r in polished if r.get("accepted") is True]
    if not applied:
        return 0

    untouched = [r for r in applied if r.get("changed_words", 0) == 0]
    print(f"  правка применилась: {len(applied)}")
    print(f"  из них ничего не изменила: {len(untouched)}"
          + (f" — {sum(r['llm_s'] for r in untouched):.0f} с ожидания впустую"
             if untouched else ""))

    words = sum(r.get("raw_words", 0) for r in applied)
    touched = sum(r.get("changed_words", 0) for r in applied)
    if words:
        print(f"  глубина вмешательства: {touched} из {words} слов ({100 * touched / words:.1f}%)")

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
        print(f"\n  {r['at']}  тронуто {r['changed_words']}/{r['raw_words']} слов ({share:.0f}%)"
              f"   {r['llm_s']:.1f} с")
        print(f"    было : {r['raw'][:160]}")
        print(f"    стало: {r['final'][:160]}")

    leaked = [r for r in applied if r.get("response") and r["response"].strip() != r.get("polished")]
    if leaked:
        block("Ответы, которые пришлось чистить от обёрток")
        print(f"  таких записей: {len(leaked)} — модель приписывает разметку к ответу")
        for r in leaked[:3]:
            print(f"    {r['at']}: {r['response'][:120]!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
