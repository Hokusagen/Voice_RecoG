"""Точка входа VoiceTyper."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import logging_setup  # noqa: E402

# Собранное приложение живёт без консоли, поэтому вывод заворачивается в файл
# до первого print — иначе диагностика сбоя невозможна в принципе.
_LOG_PATH = logging_setup.redirect_output()

from core import cuda_paths  # noqa: E402

# Каталоги CUDA нужно прописать до того, как что-либо потянет ctranslate2:
# загрузчик ищет DLL в момент импорта расширения и второго шанса не даёт.
_CUDA_DIRS = cuda_paths.setup()

from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from config import Config  # noqa: E402
from controller import Controller  # noqa: E402
from ui import theme  # noqa: E402

_MUTEX_NAME = "VoiceTyper.SingleInstance"
_ERROR_ALREADY_EXISTS = 183

#: Мьютекс живёт, пока открыт дескриптор, поэтому ссылку надо держать: без неё
#: сборщик мусора закроет его, и следующий запуск решит, что он первый.
_mutex_handle = None


def _already_running() -> bool:
    """Второй экземпляр повесил бы второй хук — и каждая клавиша сработала бы дважды."""
    global _mutex_handle
    if sys.platform != "win32":
        return False
    import ctypes

    # Именно WinDLL(use_last_error=True) и ctypes.get_last_error(): вызов
    # kernel32.GetLastError() как отдельной функции возвращает код уже после
    # того, как ctypes сбросил его своим служебным вызовом, — проверка молча
    # пропускала второй экземпляр.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]

    _mutex_handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    return ctypes.get_last_error() == _ERROR_ALREADY_EXISTS


def main() -> int:
    if _already_running():
        print("VoiceTyper уже запущен.")
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("VoiceTyper")
    app.setApplicationDisplayName("Голосовой ввод")
    # HUD прячется между диктовками, и без этого приложение закрывалось бы
    # вместе с последним окном.
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("Системный трей недоступен — работать негде.")
        return 1

    if _LOG_PATH is not None:
        print(f"[log] {_LOG_PATH}")
    print(f"[cuda] каталоги DLL: {_CUDA_DIRS or 'рядом с ctranslate2'}")

    cfg = Config.load()
    # Шрифты обязаны быть зарегистрированы до создания первого QFont.
    print(f"[ui] шрифт: {theme.init_fonts(cfg.ui.font)}")

    controller = Controller(cfg)
    controller.start()
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 — последний рубеж перед тишиной
        logging_setup.report(exc)
        sys.exit(1)
