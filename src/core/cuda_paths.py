"""Регистрация каталогов с CUDA-DLL.

Импортировать нужно до ctranslate2/faster_whisper: загрузчик C++ ищет
cublas64_12.dll и cudnn64_9.dll в момент импорта расширения, и если каталогов
нет в PATH, импорт падает с невнятной ошибкой про отсутствующий модуль.

Нужно это при запуске из исходников: в venv библиотеки лежат в
site-packages/nvidia/<пакет>/bin, далеко от самого расширения. В собранном
приложении PyInstaller кладёт их рядом с ctranslate2, где Windows находит их
сама, поэтому setup() там честно ничего не находит и не должен.
"""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path


def _candidate_roots() -> list[Path]:
    """Где может лежать пакет nvidia — в собранном .exe и в исходниках."""
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        # onedir-сборка PyInstaller распаковывает данные в _internal/.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
        roots.append(Path(sys.executable).parent)
    else:
        # Внутри venv site-packages лежит в <prefix>/Lib/site-packages, а не
        # рядом с python.exe: путь от os.path.dirname(sys.executable) указывает
        # в Scripts/ и не существует.
        purelib = sysconfig.get_paths().get("purelib")
        if purelib:
            roots.append(Path(purelib))
        roots.append(Path(sys.prefix) / "Lib" / "site-packages")
    return roots


def setup() -> list[str]:
    """Добавляет найденные каталоги в PATH и в список DLL-директорий.

    Возвращает то, что реально нашлось, — удобно печатать в лог, чтобы
    отличить «CUDA не настроена» от «CUDA нет на машине».
    """
    if sys.platform != "win32":
        return []

    found: list[str] = []
    seen: set[str] = set()

    for root in _candidate_roots():
        nvidia_dir = root / "nvidia"
        if not nvidia_dir.is_dir():
            continue
        for bin_dir in sorted(nvidia_dir.glob("*/bin")):
            key = str(bin_dir).lower()
            if key in seen or not bin_dir.is_dir():
                continue
            seen.add(key)
            found.append(str(bin_dir))

    if not found:
        return []

    os.environ["PATH"] = os.pathsep.join(found + [os.environ.get("PATH", "")])
    for path in found:
        try:
            os.add_dll_directory(path)
        except OSError:
            # Каталог мог исчезнуть между glob и вызовом — PATH уже прописан.
            pass
    return found
