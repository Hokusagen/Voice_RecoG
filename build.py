"""Пересборка .exe одной командой.

    python build.py             спросит подтверждение, соберёт, запустит обратно
    python build.py --yes       без вопросов
    python build.py --no-run    собрать, но не запускать
    python build.py --lite      лёгкая сборка: без faster-whisper и CUDA, только облако

Ручная сборка спотыкается об одно и то же: работающий VoiceTyper держит
собственный .exe открытым, PyInstaller падает на записи, а после сборки
приложение надо не забыть поднять. Скрипт делает всё три шага по порядку.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from config import APP_VERSION  # noqa: E402  — путь настраивается выше

SPEC = ROOT / "VoiceTyper.spec"
LITE = "--lite" in sys.argv
NAME = "VoiceTyper-lite" if LITE else "VoiceTyper"
EXE = ROOT / "dist" / NAME / f"{NAME}.exe"
CHANGELOG = ROOT / "CHANGELOG.md"


def head_note() -> str:
    """Первый абзац свежей записи в истории версий."""
    if not CHANGELOG.exists():
        return ""
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.startswith("## "):
            body = [ln for ln in lines[index + 1 : index + 8] if ln.strip()]
            return line[3:] + "\n    " + "\n    ".join(body[:6])
    return ""


def locked() -> bool:
    """Занят ли .exe работающим приложением."""
    if not EXE.exists():
        return False
    try:
        with EXE.open("r+b"):
            return False
    except OSError:
        return True


def stop() -> bool:
    """Просит приложение закрыться, при упорстве снимает принудительно."""
    if not locked():
        return True
    print("  VoiceTyper запущен — закрываю")
    subprocess.run(["taskkill", "/IM", f"{NAME}.exe"], capture_output=True)
    for _ in range(20):
        if not locked():
            return True
        time.sleep(0.25)

    print("  не закрылся по-хорошему — снимаю принудительно")
    subprocess.run(["taskkill", "/F", "/IM", f"{NAME}.exe"], capture_output=True)
    for _ in range(20):
        if not locked():
            return True
        time.sleep(0.25)
    return False


def size_mb(folder: Path) -> float:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) / 1024 / 1024


def main(argv: list[str]) -> int:
    yes = "--yes" in argv or "-y" in argv
    run_after = "--no-run" not in argv

    print(f"\nСборка {NAME} {APP_VERSION}\n")
    note = head_note()
    if note:
        print(f"  {note}\n")
    if APP_VERSION not in CHANGELOG.read_text(encoding="utf-8"):
        print(f"  ⚠ версии {APP_VERSION} нет в CHANGELOG.md — стоит дописать\n")

    if not yes:
        try:
            if input("  Собирать? [y/N] ").strip().lower() not in ("y", "yes", "д", "да"):
                print("  отменено")
                return 1
        except EOFError:
            print("  нечем спросить подтверждение — запустите с --yes")
            return 1

    if not stop():
        print("  не удалось освободить .exe, сборка невозможна")
        return 1

    started = time.monotonic()
    print("\n  PyInstaller пошёл, это минуты…\n")
    env = dict(os.environ, VOICETYPER_LITE="1" if LITE else "", VOICETYPER_VERSION=APP_VERSION)
    result = subprocess.run(
        [str(ROOT / "venv" / "Scripts" / "pyinstaller.exe"), str(SPEC), "--noconfirm"],
        cwd=ROOT,
        env=env,
    )
    if result.returncode != 0:
        print(f"\n  сборка провалилась, код {result.returncode}")
        return result.returncode

    took = time.monotonic() - started
    print(f"\n  Готово за {took / 60:.1f} мин: {EXE}")
    print(f"  версия {APP_VERSION}, каталог {size_mb(EXE.parent):.0f} МБ")

    if run_after:
        subprocess.Popen([str(EXE)], cwd=EXE.parent)
        print("  приложение запущено")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
