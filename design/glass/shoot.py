"""Снимки концепта в безголовом Edge: состояние × фон × момент времени.

    python shoot.py <id> [стадия/фон/мс ...]
    python shoot.py lens listening/code/1500 done/photo/3500 done/photo/3500/flat

Без аргументов после id снимает стандартный набор. PNG кладёт в shots/<id>/,
в конце печатает пути и строки консоли с ошибками (шейдер, исключения).
"""

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DEFAULT = ["listening/code/1800", "listening/doc/2600", "transcribing/photo/1600",
           "done/photo/2600", "done/doc/1400", "error/code/900"]


def shoot(concept: str, spec: str) -> tuple[Path, list[str]]:
    parts = spec.split("/")
    stage, scene, ms = parts[:3]
    flat = "/flat" if len(parts) > 3 and parts[3] == "flat" else ""
    out_dir = HERE / "shots" / concept
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{stage}_{scene}_{ms}{flat.replace('/', '_')}.png"
    url = f"file:///{HERE.as_posix()}/solo.html#{concept}/{stage}/{scene}/0{flat}"
    # Свой профиль на каждый концепт: иначе вызов уходит в уже запущенный Edge
    # (у пользователя он висит в фоне) и молча ничего не снимает.
    profile = Path(tempfile.gettempdir()) / f"vt-edge-{concept}"
    cmd = [EDGE, "--headless=new", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
           "--enable-unsafe-swiftshader", "--hide-scrollbars", "--window-size=1040,420",
           f"--virtual-time-budget={ms}", "--enable-logging=stderr", "--log-level=0",
           f"--screenshot={out}", url]
    run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    noise = ("GPU", "gpu", "SwiftShader", "DevTools", "Fontconfig", "dbus", "sandbox", "Skia")
    errors = [line for line in (run.stderr or "").splitlines()
              if ("CONSOLE" in line or "Uncaught" in line or "ERROR:" in line)
              and not any(n in line for n in noise)]
    return out, errors


def main() -> None:
    concept = sys.argv[1]
    specs = sys.argv[2:] or DEFAULT
    for spec in specs:
        path, errors = shoot(concept, spec)
        print(f"{spec}: {path}" + ("" if path.exists() else "  (СНИМКА НЕТ)"))
        for line in errors[:12]:
            print("   ", line[:300])


if __name__ == "__main__":
    main()
