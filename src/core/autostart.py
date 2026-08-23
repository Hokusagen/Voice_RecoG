"""Автозапуск вместе с Windows через ветку реестра Run текущего пользователя.

HKEY_CURRENT_USER не требует прав администратора и не трогает настройки системы
целиком — правится только автозагрузка самого пользователя.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # pragma: no cover — приложение рассчитано на Windows
    winreg = None

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE = "VoiceTyper"


def _command() -> str:
    """Строка запуска — по-разному для .exe и для запуска из исходников."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable)}"'
    script = Path(__file__).resolve().parents[1] / "main.py"
    # pythonw.exe запускает без консольного окна.
    launcher = Path(sys.executable).with_name("pythonw.exe")
    if not launcher.exists():
        launcher = Path(sys.executable)
    return f'"{launcher}" "{script}"'


def is_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    """Включает или выключает автозапуск. Возвращает фактическое состояние."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _VALUE, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(key, _VALUE)
                except FileNotFoundError:
                    pass
        return enabled
    except OSError as exc:
        print(f"[autostart] не удалось изменить автозапуск: {exc}")
        return is_enabled()
