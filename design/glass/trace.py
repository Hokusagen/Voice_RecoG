"""Трасса движения концепта: числа по кадрам стадии, без глаз и без видео.

    python trace.py <id> <спек> [--every 0.1] [--json]
    python trace.py grain listening/photo/t=4
    python trace.py grain done-joy/photo/t=1.2/lively --every 0.05

Спек как у shoot.py (стадия/фон/t=секунды[/flat][/lively][/cold]). Страница
прогоняет стадию в замороженном времени от 0 до t и складывает по каждому кадру
уровень голоса, прозрачность подписи и всё, что концепт вернул из frame() в поле
trace (например {w: ширина, r: радиус зерна}).

Печатает таблицу с шагом --every и для каждого числа «дрожь» — долю размаха
на частотах слогов (3–8 Гц). Голос должен модулировать форму фразами: дрожь
выше ~0.25 значит, что форма дёргается на каждом слоге.
"""

import html
import json
import math
import re
import sys

from shoot import cleanup, edge, parse, url_for


# Консоль Windows по умолчанию в cp1251: без этого кириллица в выводе превращается в «????».
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load(concept: str, spec: str) -> dict:
    p = parse(spec)
    if "t" not in p["opts"]:
        raise SystemExit("Трассе нужен t=секунды в спеке")
    run = edge(concept, url_for(concept, p, {"trace": "1"}), dump_dom=True)
    m = re.search(r'<pre id="lg-trace" hidden="">(.*?)</pre>', run.stdout or "", re.S)
    if not m:
        tail = (run.stderr or "")[-1500:]
        raise SystemExit(f"Трассы нет на странице. Вывод Edge:\n{tail}")
    return json.loads(html.unescape(m.group(1)))


def band_share(xs: list[float], dt: float, lo: float = 3.0, hi: float = 8.0) -> float:
    """Доля дисперсии ряда в полосе lo..hi Гц (ДПФ, окно Ханна)."""
    n = len(xs)
    if n < 16:
        return 0.0
    mean = sum(xs) / n
    ys = [(x - mean) * (0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1))) for i, x in enumerate(xs)]
    total = band = 0.0
    for k in range(1, n // 2):
        f = k / (n * dt)
        re_ = sum(y * math.cos(2 * math.pi * k * i / n) for i, y in enumerate(ys))
        im_ = sum(y * math.sin(2 * math.pi * k * i / n) for i, y in enumerate(ys))
        e = re_ * re_ + im_ * im_
        total += e
        if lo <= f <= hi:
            band += e
    return band / total if total > 1e-12 else 0.0


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return
    concept, spec = args[0], args[1]
    every = 0.1
    as_json = "--json" in args
    if "--every" in args:
        every = float(args[args.index("--every") + 1])
    try:
        data = load(concept, spec)
    finally:
        cleanup(concept)
    if data.get("error"):
        print("ОШИБКА КОНЦЕПТА:", data["error"])
    frames = data["frames"]
    if as_json:
        print(json.dumps(data, ensure_ascii=False))
        return
    keys = sorted({k for f in frames for k in f["trace"].keys()})
    head = ["t", "level", "speech", "label"] + keys
    print("  ".join(f"{h:>8}" for h in head))
    next_t = 0.0
    for f in frames:
        if f["t"] + 1e-9 < next_t:
            continue
        next_t += every
        row = [f["t"], f["level"], f["speech"], f["label"]] + [f["trace"].get(k, float("nan")) for k in keys]
        print("  ".join(f"{v:8.3f}" if isinstance(v, (int, float)) else f"{str(v):>8}" for v in row)
              + ("  " + ",".join(f["events"]) if f["events"] else ""))
    dt = frames[1]["t"] - frames[0]["t"] if len(frames) > 1 else 1 / 60
    print()
    print("дрожь (доля размаха на 3–8 Гц, выше ~0.25 — дёргается на слогах):")
    for k in ["level"] + keys:
        xs = [f["level"] if k == "level" else f["trace"].get(k) for f in frames]
        xs = [x for x in xs if isinstance(x, (int, float))]
        if len(xs) < 16:
            continue
        span = max(xs) - min(xs)
        print(f"  {k:>12}: {band_share(xs, dt):.2f}   размах {span:.3f}")
    lab = data.get("label")
    if lab:
        print()
        print("подпись в последнем кадре:", json.dumps(lab, ensure_ascii=False))


if __name__ == "__main__":
    main()
