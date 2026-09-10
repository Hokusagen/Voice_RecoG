"""Ярлык, который всегда запускает свежий код.

    python shortcut.py            создать VoiceTyper.lnk в каталоге проекта
    python shortcut.py --pin      заодно перенацелить ярлык на панели задач
    python shortcut.py --exe      вернуть ярлыки на собранный .exe

Собранный .exe устаревает ровно в тот момент, когда меняется исходник, а
закреплённая на панели задач иконка продолжает молча запускать позавчерашнюю
сборку — и понять это можно только по номеру версии в подсказке трея. Ярлык на
pythonw.exe + src/main.py так не умеет: он запускает то, что лежит в каталоге
прямо сейчас, и после коммита пересобирать нечего.

build.py остаётся для того, ради чего он и есть: собрать то, что можно отдать
на чужую машину, где ни Python, ни venv нет.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

ICON = ROOT / "assets" / "voicetyper.ico"
LINK = ROOT / "VoiceTyper.lnk"
EXE = ROOT / "dist" / "VoiceTyper" / "VoiceTyper.exe"

_NOTE = "Голосовой ввод: зажал клавишу, продиктовал, отпустил"


def taskbar_link() -> Path:
    """Где Windows держит ярлыки, закреплённые на панели задач."""
    return (
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft" / "Internet Explorer" / "Quick Launch"
        / "User Pinned" / "TaskBar" / "VoiceTyper.lnk"
    )


def source_command() -> tuple[Path, str]:
    """Чем запускать исходники.

    pythonw.exe, а не python.exe: у второго за приложением остаётся чёрное
    консольное окно на всё время работы.
    """
    launcher = ROOT / "venv" / "Scripts" / "pythonw.exe"
    if not launcher.exists():
        launcher = Path(sys.executable).with_name("pythonw.exe")
    return launcher, f'"{ROOT / "src" / "main.py"}"'


def make_icon() -> Path:
    """Рисует .ico той же функцией, что рисует иконку в трее.

    Своего файла с иконкой у проекта не было вовсе: в трее она рисуется кодом,
    а собранный .exe так и ходил с иконкой PyInstaller по умолчанию.
    """
    from PySide6.QtWidgets import QApplication

    from ui.tray import app_icon

    app = QApplication.instance() or QApplication([])
    ICON.parent.mkdir(parents=True, exist_ok=True)
    if not app_icon().pixmap(256, 256).save(str(ICON), "ICO"):
        raise RuntimeError(f"не удалось записать {ICON}")
    del app
    return ICON


def write_link(path: Path, target: Path, arguments: str, workdir: Path) -> None:
    import win32com.client

    link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(path))
    link.TargetPath = str(target)
    link.Arguments = arguments
    link.WorkingDirectory = str(workdir)
    link.IconLocation = f"{ICON},0"
    link.Description = _NOTE
    link.Save()


def describe(path: Path) -> str:
    import win32com.client

    link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(path))
    return " ".join(part for part in (link.TargetPath, link.Arguments) if part)


def main(argv: list[str]) -> int:
    if sys.platform != "win32":
        print("ярлыки умеет делать только Windows")
        return 1

    if "--exe" in argv:
        if not EXE.exists():
            print(f"собранного приложения нет: {EXE}\n  соберите его: python build.py")
            return 1
        target, arguments, workdir = EXE, "", EXE.parent
        print(f"Ярлыки на собранное приложение: {EXE}")
        print("  оно устаревает при каждой правке исходников — пересобирать через build.py")
    else:
        target, arguments = source_command()
        workdir = ROOT
        if not target.exists():
            print(f"не нашёл {target}\n  создайте venv: python -m venv venv")
            return 1
        print(f"Ярлыки на исходники: {target.name} {arguments}")
        print("  запускается то, что лежит в каталоге сейчас — пересобирать не надо")

    make_icon()
    print(f"  иконка: {ICON}")

    write_link(LINK, target, arguments, workdir)
    print(f"  ярлык : {LINK}")

    pinned = taskbar_link()
    if "--pin" not in argv:
        print("\nЧтобы закрепить: правый клик по ярлыку -> Закрепить на панели задач.")
        print("Чтобы перенацелить уже закреплённый: python shortcut.py --pin")
        return 0

    if not pinned.exists():
        print(f"\nна панели задач ярлыка нет ({pinned});\n  закрепите {LINK.name} вручную — он уже готов")
        return 0

    was = describe(pinned)
    write_link(pinned, target, arguments, workdir)
    print(f"\nЯрлык на панели задач перенацелен:\n  было : {was}\n  стало: {describe(pinned)}")
    # Windows держит подпись и иконку закреплённой кнопки в своём кэше и
    # обновляет их не сразу; сам запуск при этом идёт уже по новой цели.
    print("Иконка на панели может обновиться не сразу — цель уже новая.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
