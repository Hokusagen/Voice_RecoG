"""Контраст подписи по худшему пикселю под буквами.

    python contrast.py <id> <спек> [спек ...]
    python contrast.py grain listening/photo/t=2.4 listening/doc/t=2.4 listening/code/t=2.4

Спек как у shoot.py, с t=секунды. Для каждого снимаются два кадра одного и того же
момента: с буквами (значок скрыт) и только с ореолом (буквы прозрачные). Пиксели,
которые буквы поменяли, — маска глифов. Фон под буквами берётся из второго кадра,
то есть вместе со стеклом и ореолом, как его видит глаз. Для светлого текста худший —
самый светлый фон (95-й перцентиль), для тёмного — самый тёмный (5-й). Цвет букв —
по ядру глифов (их 10% самых контрастных пикселей), поэтому прозрачность детали
учитывается честно. Планка — 4.5:1 (WCAG AA для 13–14 px).
"""

import sys

from PIL import Image

from shoot import cleanup, parse, shoot


# Консоль Windows по умолчанию в cp1251: без этого кириллица в выводе превращается в «????».
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(px: tuple) -> float:
    r, g, b = px[:3]
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(q * (len(xs) - 1))))]


def measure(concept: str, spec: str) -> str:
    p = parse(spec)
    if "t" not in p["opts"]:
        return f"{spec}: нужен t=секунды"
    text_png, err1 = shoot(concept, spec, {"label": "text"}, suffix="_ctext")
    halo_png, err2 = shoot(concept, spec, {"label": "halo"}, suffix="_chalo")
    if not text_png.exists() or not halo_png.exists():
        return f"{spec}: снимка нет {err1[:2]} {err2[:2]}"
    a = Image.open(text_png).convert("RGB")
    b = Image.open(halo_png).convert("RGB")
    w, h = a.size
    pa, pb = a.load(), b.load()
    # Ищем глифы во всей центральной полосе: подпись всегда около плашки.
    mask = []
    for y in range(40, h - 40):
        for x in range(40, w - 40):
            ca, cb = pa[x, y], pb[x, y]
            if max(abs(ca[i] - cb[i]) for i in range(3)) > 36:
                mask.append((lum(ca), lum(cb)))
    if len(mask) < 20:
        return f"{spec}: букв не видно (подпись скрыта или прозрачна) — пикселей {len(mask)}"
    text_l = [m[0] for m in mask]
    bg_l = [m[1] for m in mask]
    light = sum(t > g for t, g in mask) > len(mask) / 2
    if light:
        text = pct(text_l, 0.9)
        worst = pct(bg_l, 0.95)
        ratio = (text + 0.05) / (worst + 0.05)
    else:
        text = pct(text_l, 0.1)
        worst = pct(bg_l, 0.05)
        ratio = (worst + 0.05) / (text + 0.05)
    med = pct(bg_l, 0.5)
    ratio_med = (max(text, med) + 0.05) / (min(text, med) + 0.05)
    verdict = "ok" if ratio >= 4.5 else "НИЖЕ 4.5"
    tone = "светлый" if light else "тёмный"
    return (f"{spec}: {ratio:.2f}:1 по худшему пикселю ({verdict}), {ratio_med:.2f}:1 по медиане; "
            f"текст {tone}, пикселей глифов {len(mask)}")


def main() -> None:
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return
    concept = args[0]
    try:
        for spec in args[1:]:
            print(measure(concept, spec))
    finally:
        cleanup(concept)


if __name__ == "__main__":
    main()
