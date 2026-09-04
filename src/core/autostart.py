"""Автозапуск вместе с системой.

Windows: ветка реестра Run текущего пользователя — без прав администратора,
правится только автозагрузка самого пользователя. macOS: LaunchAgent в
~/Library/LaunchAgents, тоже пользовательский. На остальных системах
автозапуск не поддерживается, переключатель в трее ничего не делает.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE = "VoiceTyper"
_AGENT_LABEL = "com.hokusagen.voicetyper"


def _command_parts() -> list[str]:
    """Что запускать — по-разному для собранного приложения и исходников."""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable))]
    script = Path(__file__).resolve().parents[1] / "main.py"
    launcher = Path(sys.executable)
    if sys.platform == "win32":
        # pythonw.exe запускает без консольного окна.
        windowless = launcher.with_name("pythonw.exe")
        if windowless.exists():
            launcher = windowless
    return [str(launcher), str(script)]


def _command() -> str:
    return " ".join(f'"{part}"' for part in _command_parts())


def _agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_AGENT_LABEL}.plist"


def is_enabled() -> bool:
    if sys.platform == "darwin":
        return _agent_path().exists()
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
    if sys.platform == "darwin":
        return _set_agent(enabled)
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


def _set_agent(enabled: bool) -> bool:
    path = _agent_path()
    try:
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "Label": _AGENT_LABEL,
                "ProgramArguments": _command_parts(),
                "RunAtLoad": True,
                "ProcessType": "Interactive",
            }
            with path.open("wb") as handle:
                plistlib.dump(payload, handle)
        elif path.exists():
            path.unlink()
        return enabled
    except OSError as exc:
        print(f"[autostart] не удалось изменить автозапуск: {exc}")
        return is_enabled()
