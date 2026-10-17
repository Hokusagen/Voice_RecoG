"""Точка входа VoiceTyper."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# OpenBLAS из numpy при импорте заводит поток и буфер на каждое ядро: на 12
# ядрах это 11 спящих потоков и ~350 МБ выделенной памяти. Матрицы у нас —
# кадр плашки да блок звука, им хватает одного потока. Читается один раз при
# загрузке numpy, поэтому — до любого импорта.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import logging_setup  # noqa: E402

# Без консоли, у сборки и у pythonw из ярлыка, вывод заворачивается в файл
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
        return _lock_file_taken()
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


def _lock_file_taken() -> bool:
    """macOS и Linux: файл-замок в каталоге данных, держится всё время работы."""
    global _mutex_handle
    import fcntl

    from config import app_data_dir

    try:
        handle = open(app_data_dir() / "instance.lock", "w")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    _mutex_handle = handle
    return False


def _release_instance() -> None:
    """Отпускает замок единственного экземпляра, не дожидаясь выхода процесса."""
    global _mutex_handle
    if _mutex_handle is None:
        return
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle(_mutex_handle)
    else:
        _mutex_handle.close()
    _mutex_handle = None


def _relaunch() -> None:
    """Поднимает новый экземпляр той же командой, что запустила этот.

    Из исходников это значит свежий код: перезапуск заменяет «Выход» и
    повторный клик по ярлыку после каждого коммита.
    """
    import os
    import subprocess

    if getattr(sys, "frozen", False):
        command = [sys.executable, *sys.argv[1:]]
    else:
        launcher = Path(sys.executable)
        if sys.platform == "win32" and launcher.with_name("pythonw.exe").exists():
            # Консоли у нового экземпляра не будет, а python.exe без неё
            # открывал бы окно каждой консольной утилите, которую зовёт.
            # Ярлык и автозапуск и так идут через pythonw.
            launcher = launcher.with_name("pythonw.exe")
        command = [str(launcher), *sys.argv]

    options: dict = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    # Вывод у нового экземпляра никуда не подключён, поэтому лог в файл ему
    # нужно включить явно — иначе после перезапуска из терминала он молчал бы.
    env = dict(os.environ, **{logging_setup.FORCE_ENV: "1"})
    _release_instance()
    subprocess.Popen(
        command, cwd=os.getcwd(), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **options,
    )
    print(f"[main] перезапуск: {' '.join(command)}")


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
    code = app.exec()
    if controller.restarting:
        _relaunch()
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 — последний рубеж перед тишиной
        logging_setup.report(exc)
        sys.exit(1)
