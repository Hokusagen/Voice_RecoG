"""Журнал работы и падений.

Собранное приложение запускается без консоли, поэтому print и трассировки
уходят в никуда: при сбое окно просто исчезает, и понять причину невозможно.
Здесь поток вывода перенаправляется в файл рядом с настройками, а необработанные
исключения дополнительно показываются пользователю окном.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

from config import app_data_dir

LOG_PATH = app_data_dir() / "voicetyper.log"
CRASH_PATH = app_data_dir() / "crash.log"

#: Лог перезаписывается, если разросся: это дневник последнего запуска, а не архив.
_MAX_BYTES = 512 * 1024


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def redirect_output() -> Path | None:
    """Заворачивает stdout и stderr в файл. Только для сборки без консоли."""
    if not getattr(sys, "frozen", False):
        return None
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > _MAX_BYTES:
            LOG_PATH.unlink()
        stream = LOG_PATH.open("a", encoding="utf-8", buffering=1)
    except OSError:
        return None

    sys.stdout = stream
    sys.stderr = stream
    print(f"\n===== запуск {_stamp()} =====")
    return LOG_PATH


def write_crash(exc: BaseException) -> Path | None:
    """Сохраняет трассировку и возвращает путь к файлу."""
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    print(text)
    try:
        CRASH_PATH.write_text(f"{_stamp()}\n\n{text}", encoding="utf-8")
        return CRASH_PATH
    except OSError:
        return None


def report(exc: BaseException) -> None:
    """Показывает причину падения окном — иначе пользователь увидит пустоту."""
    path = write_crash(exc)
    where = f"\n\nПодробности: {path}" if path else ""
    message = f"{type(exc).__name__}: {exc}{where}"

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is not None:
            QMessageBox.critical(None, "VoiceTyper не запустился", message)
            return
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "VoiceTyper не запустился", 0x10)
        except Exception:
            pass
