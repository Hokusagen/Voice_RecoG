"""Снимки концепта в безголовом Edge.

    python shoot.py <id> [спек ...]
    python shoot.py grain listening/photo/t=2.4 done-joy/doc/t=0.35 error/code/t=0.6/flat
    python shoot.py grain --series listening/photo/0.2:3.0:0.2 [--series ...]

Спек второго круга: стадия/фон/t=секунды[/flat][/lively][/cold][/label=text|halo|none].
Время замороженное: часы основы идут шагом 1/60 с до момента t от начала стадии —
до неё настоящий путь «слушаю → распознаю → причёсываю», — и рисуется один кадр.
Стадии: listening, transcribing, polishing, done, done-joy, done-sad, error и
hidden (уход после «Готово»). lively — темперамент «живее», cold — в стадию сразу
из невидимого состояния.

Старый спек первого круга «стадия/фон/мс[/flat]» — живое время с виртуальным
бюджетом; он ненадёжен и ловит начало появления.

--series стадия/фон/от:до:шаг[/flat][/lively] снимает ряд моментов и склеивает
лист shots/<id>/series_<...>.png с подписями времени — так видно движение.

PNG кладёт в shots/<id>/ (с VT_TAG=метка — в shots/<id>/<метка>/, и профиль Edge
у метки свой: так параллельные агенты не мешают друг другу), печатает пути и строки консоли с ошибками. В конце
завершает свои процессы Edge (профиль vt-edge-<id>): висящие процессы копились
десятками, съедали память, и Edge переставал запускаться.
"""

import os
import re
import subprocess
import time
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DEFAULT = ["listening/code/t=2.2", "listening/doc/t=2.6", "transcribing/photo/t=0.9",
           "done/photo/t=0.3", "done-joy/doc/t=0.35", "done-sad/photo/t=0.6", "error/code/t=0.5"]
# Метка агента: у каждого свой профиль Edge и своя папка снимков, иначе два
# параллельных запуска делят один Edge и затирают друг другу файлы.
TAG = re.sub(r"[^\w-]", "", os.environ.get("VT_TAG", ""))
NOISE = ("GPU", "gpu", "SwiftShader", "DevTools", "Fontconfig", "dbus", "sandbox", "Skia", "vbs_encoder",
         "task_manager", "chrome-extension://", "ProtocolLaunch")


# Консоль Windows по умолчанию в cp1251: без этого кириллица в выводе превращается в «????».
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def parse(spec: str) -> dict:
    """Спек → параметры страницы и имя файла."""
    parts = spec.split("/")
    stage, scene = parts[0], parts[1]
    rest = parts[2:]
    p = {"stage": stage, "scene": scene, "flat": False, "opts": {}, "legacy_ms": None}
    for part in rest:
        if part.startswith("t="):
            p["opts"]["t"] = part[2:]
        elif part == "flat":
            p["flat"] = True
        elif part == "lively":
            p["opts"]["temper"] = "1"
        elif part == "cold":
            p["opts"]["cold"] = "1"
        elif part.startswith("label="):
            p["opts"]["label"] = part[6:]
        elif part.isdigit():
            p["legacy_ms"] = int(part)
        elif part:
            raise SystemExit(f"Непонятная часть спека «{part}» в {spec}")
    if "t" not in p["opts"] and p["legacy_ms"] is None:
        raise SystemExit(f"В спеке {spec} нет ни t=секунды, ни мс")
    name = "_".join(x for x in parts if x).replace("=", "").replace(".", "_")
    p["name"] = name
    return p


def url_for(concept: str, p: dict, extra: dict | None = None) -> str:
    opts = dict(p["opts"])
    if extra:
        opts.update(extra)
    flat = "flat" if p["flat"] else ""
    opt_str = "&".join(f"{k}={v}" for k, v in opts.items())
    return f"file:///{HERE.as_posix()}/solo.html#{concept}/{p['stage']}/{p['scene']}/0/{flat}/{opt_str}"


def profile_name(concept: str) -> str:
    return f"vt-edge-{concept}" + (f"-{TAG}" if TAG else "")


def profile(concept: str) -> Path:
    # Свой профиль на каждый концепт: иначе вызов уходит в уже запущенный Edge
    # (у пользователя он висит в фоне) и молча ничего не снимает.
    return Path(tempfile.gettempdir()) / profile_name(concept)


def shots_dir(concept: str) -> Path:
    return HERE / "shots" / concept / TAG if TAG else HERE / "shots" / concept


def edge(concept: str, url: str, *, screenshot: Path | None = None, budget_ms: int = 1500,
         dump_dom: bool = False, timeout: int = 120) -> subprocess.CompletedProcess:
    """Запуск безголового Edge. Снимок готов за ~1.5 с, но потом Edge на этой машине
    ещё ~19 с не выходит, поэтому ждём сам результат и завершаем процесс сами."""
    cmd = [EDGE, "--headless=new", f"--user-data-dir={profile(concept)}", "--no-first-run",
           "--no-default-browser-check", "--enable-unsafe-swiftshader", "--hide-scrollbars",
           "--window-size=1040,420", f"--virtual-time-budget={budget_ms}", "--enable-logging=stderr",
           "--log-level=0", "--disable-extensions", "--disable-background-networking"]
    if screenshot is not None:
        cmd.append(f"--screenshot={screenshot}")
    if dump_dom:
        cmd.append("--dump-dom")
    cmd.append(url)
    with tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as out:
        proc = subprocess.Popen(cmd, stdout=out, stderr=err)
        start = time.monotonic()
        try:
            while proc.poll() is None and time.monotonic() - start < timeout:
                if screenshot is not None and png_ready(screenshot):
                    break
                if dump_dom:
                    out.seek(0)
                    if b"</html>" in out.read():
                        break
                time.sleep(0.05)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(10)
        out.seek(0)
        err.seek(0)
        stdout = out.read().decode("utf-8", "replace")
        stderr = err.read().decode("utf-8", "replace")
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def png_ready(path: Path) -> bool:
    """PNG дописан целиком: заканчивается блоком IEND."""
    try:
        with open(path, "rb") as f:
            f.seek(-12, 2)
            return f.read()[4:8] == b"IEND"
    except OSError:
        return False


def console_errors(run: subprocess.CompletedProcess) -> list[str]:
    return [line for line in (run.stderr or "").splitlines()
            if ("CONSOLE" in line or "Uncaught" in line or "ERROR:" in line)
            and not any(n in line for n in NOISE)]


def shoot(concept: str, spec: str, extra: dict | None = None, suffix: str = "") -> tuple[Path, list[str]]:
    p = parse(spec)
    out_dir = shots_dir(concept)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{p['name']}{suffix}.png"
    if out.exists():
        out.unlink()
    budget = p["legacy_ms"] if p["legacy_ms"] is not None else 1500
    run = edge(concept, url_for(concept, p, extra), screenshot=out, budget_ms=budget)
    return out, console_errors(run)


def cleanup(concept: str) -> int:
    """Завершить висящие процессы Edge этого концепта — только с его профилем."""
    # Точное имя профиля: vt-edge-grain не должен задеть vt-edge-grain-critic.
    tag = profile_name(concept)
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
          f"Where-Object {{ $_.CommandLine -match '{tag}(\"|\\s|$)' }} | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; 1 } | Measure-Object | "
          "Select-Object -ExpandProperty Count")
    run = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    try:
        return int((run.stdout or "0").strip() or 0)
    except ValueError:
        return 0


def frange(a: float, b: float, step: float) -> list[float]:
    out, x = [], a
    while x <= b + 1e-9:
        out.append(round(x, 4))
        x += step
    return out


def series(concept: str, spec: str) -> Path:
    """Ряд моментов стадии и лист с подписями времени."""
    parts = spec.split("/")
    stage, scene, span = parts[0], parts[1], parts[2]
    tail = "/".join(parts[3:])
    a, b, step = (float(x) for x in span.split(":"))
    shots = []
    for t in frange(a, b, step):
        s = f"{stage}/{scene}/t={t}" + (f"/{tail}" if tail else "")
        path, errors = shoot(concept, s)
        print(f"{s}: {path}" + ("" if path.exists() else "  (СНИМКА НЕТ)"))
        for line in errors[:6]:
            print("   ", line[:300])
        shots.append((t, path))
    name = "_".join([stage, scene, span.replace(":", "-").replace(".", "_")] + ([tail.replace("/", "_")] if tail else []))
    sheet = shots_dir(concept) / f"series_{name}.png"
    make_sheet(shots, sheet)
    return sheet


def make_sheet(shots: list[tuple[float, Path]], out: Path) -> None:
    """Лист: обрезка вокруг плашки (центральная полоса), по 3 кадра в ряд, подпись t."""
    from PIL import Image, ImageDraw, ImageFont
    crop = (220, 110, 820, 330)   # стадия 1000×380 со сдвигом 20 px; плашка в центре
    cw, ch = crop[2] - crop[0], crop[3] - crop[1]
    cols = 3
    rows = (len(shots) + cols - 1) // cols
    sheet = Image.new("RGB", (cw * cols, ch * rows), "#000")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("segoeui.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    for i, (t, path) in enumerate(shots):
        x, y = (i % cols) * cw, (i // cols) * ch
        if path.exists():
            sheet.paste(Image.open(path).convert("RGB").crop(crop), (x, y))
        draw.rectangle([x, y, x + 64, y + 22], fill="#000")
        draw.text((x + 6, y + 2), f"t={t:g}", fill="#ff0", font=font)
    sheet.save(out)
    print(f"лист: {out}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    concept = args[0]
    specs, series_specs = [], []
    it = iter(args[1:])
    for a in it:
        if a == "--series":
            series_specs.append(next(it))
        else:
            specs.append(a)
    if not specs and not series_specs:
        specs = DEFAULT
    try:
        for spec in specs:
            path, errors = shoot(concept, spec)
            print(f"{spec}: {path}" + ("" if path.exists() else "  (СНИМКА НЕТ)"))
            for line in errors[:12]:
                print("   ", line[:300])
        for spec in series_specs:
            series(concept, spec)
    finally:
        killed = cleanup(concept)
        if killed:
            print(f"завершено висящих процессов Edge: {killed}")


if __name__ == "__main__":
    main()
