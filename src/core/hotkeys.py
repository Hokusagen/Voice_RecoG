"""Глобальные горячие клавиши.

Прошлая версия опрашивала keyboard.is_pressed в цикле каждые 20 мс: это и грело
процессор впустую, и теряло короткие нажатия между итерациями. Здесь стоит
низкоуровневый хук, который сам будит нас на событии клавиатуры.

Состояние клавиш считается по самим событиям, а не через keyboard.is_pressed:
хуки библиотеки вызываются из очереди, и к моменту обработки нажатия клавишу
уже могли отпустить — короткий тап в режиме «нажать / нажать» просто пропал бы.

Хук живёт в собственном потоке библиотеки, поэтому наружу состояние уходит
сигналами Qt: доставка в поток GUI — забота очереди событий.

Источник событий зависит от системы: на Windows это библиотека keyboard, на
macOS — pynput (keyboard там требует root, pynput — только разрешения
«Универсальный доступ» в настройках). Логика сочетаний общая, бэкенд лишь
превращает свои события в пары «имя клавиши, нажата ли».
"""

from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtCore import QObject, Signal

from config import HotkeysConfig

#: Действия в порядке убывания специфичности: ctrl+f8 должен побеждать f8,
#: иначе одно нажатие поднимет сразу оба.
_ACTIONS = ("record_raw", "record_alt", "record")

#: Синонимы модификаторов из конфига: люди пишут «control», «win», «command».
_ALIASES = {
    "control": "ctrl",
    "win": "windows",
    "super": "windows",
    "meta": "windows",
    "command": "cmd",
    "option": "alt",
    "escape": "esc",
}


def normalize(name: str) -> str:
    name = name.strip().lower()
    return _ALIASES.get(name, name)


class HotkeyListener(QObject):
    pressed = Signal(str)
    released = Signal(str)
    cancelled = Signal()

    def __init__(self, cfg: HotkeysConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self._enabled = True
        self._active: str | None = None
        self._backend: _Backend | None = None

        self._keys: dict[str, frozenset[str]] = {}
        self._order: list[str] = []
        self._watched: set[str] = set()
        self._cancel_key = ""
        self._down: set[str] = set()

    # ---------- подписка ----------

    def start(self) -> None:
        combos = {
            name: getattr(self.cfg, name, "").strip().lower()
            for name in _ACTIONS
            if getattr(self.cfg, name, "").strip()
        }
        self._keys = {
            name: frozenset(normalize(part) for part in combo.split("+") if part.strip())
            for name, combo in combos.items()
        }
        # Сначала сочетания из большего числа клавиш.
        self._order = sorted(self._keys, key=lambda name: -len(self._keys[name]))

        self._cancel_key = normalize(self.cfg.cancel or "")
        self._watched = {key for keys in self._keys.values() for key in keys}
        if self._cancel_key:
            self._watched.add(self._cancel_key)

        self._down.clear()
        self._backend = _make_backend(self._on_key)
        self._backend.start()
        if self.cfg.suppress:
            self._backend.suppress(self.cfg.record.strip().lower())

    def stop(self) -> None:
        if self._backend is not None:
            self._backend.stop()
            self._backend = None

    # ---------- состояние ----------

    def set_enabled(self, enabled: bool) -> None:
        """Пауза: хук остаётся, но события не превращаются в действия."""
        self._enabled = enabled
        if not enabled and self._active is not None:
            name, self._active = self._active, None
            self.released.emit(name)

    # ---------- обработка событий ----------

    def _on_key(self, name: str, is_down: bool) -> None:
        if name not in self._watched:
            return

        if is_down:
            self._down.add(name)
        else:
            self._down.discard(name)

        if is_down and name == self._cancel_key:
            self.cancelled.emit()
            return

        if self._enabled:
            self._reevaluate(is_down)

    def _reevaluate(self, is_down: bool) -> None:
        if self._active is not None:
            if not self._keys[self._active] <= self._down:
                name, self._active = self._active, None
                self.released.emit(name)
            return

        # Новое действие начинается только по нажатию: иначе после снятия паузы
        # с зажатой клавишей его запустило бы любое нажатие модификатора.
        if not is_down:
            return
        for action in self._order:
            if self._keys[action] <= self._down:
                self._active = action
                self.pressed.emit(action)
                return


# ---------- бэкенды ----------

_Handler = Callable[[str, bool], None]


class _Backend:
    def __init__(self, handler: _Handler) -> None:
        self._handler = handler

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def suppress(self, combo: str) -> None:
        """Прятать нажатие от активного окна; не везде возможно."""


class _KeyboardBackend(_Backend):
    """Windows: библиотека keyboard, низкоуровневый хук."""

    def __init__(self, handler: _Handler) -> None:
        super().__init__(handler)
        import keyboard

        self._keyboard = keyboard
        self._hook = None
        self._blocked_key: str | None = None

    def start(self) -> None:
        self._hook = self._keyboard.hook(self._on_event)

    def stop(self) -> None:
        if self._hook is not None:
            try:
                self._keyboard.unhook(self._hook)
            except (KeyError, ValueError):
                pass
            self._hook = None
        if self._blocked_key is not None:
            try:
                self._keyboard.unblock_key(self._blocked_key)
            except (KeyError, ValueError):
                pass
            self._blocked_key = None

    def suppress(self, combo: str) -> None:
        if "+" in combo:
            print("[hotkeys] скрывать нажатие можно только для одиночной клавиши")
            return
        try:
            self._keyboard.block_key(combo)
            self._blocked_key = combo
        except (ValueError, KeyError) as exc:
            print(f"[hotkeys] не удалось перехватить {combo}: {exc}")

    def _on_event(self, event) -> None:
        name = normalize(event.name or "")
        # keyboard различает левый и правый модификаторы именами вида
        # «left ctrl»; в конфиге пишут просто «ctrl».
        for prefix in ("left ", "right "):
            if name.startswith(prefix):
                name = name[len(prefix):]
        self._handler(name, event.event_type == self._keyboard.KEY_DOWN)


class _PynputBackend(_Backend):
    """macOS и Linux: pynput. На macOS нужно разрешение «Универсальный доступ»."""

    _SPECIAL = {
        "ctrl_l": "ctrl", "ctrl_r": "ctrl", "ctrl": "ctrl",
        "shift_l": "shift", "shift_r": "shift", "shift": "shift",
        "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt", "alt": "alt",
        "cmd_l": "cmd", "cmd_r": "cmd", "cmd": "cmd",
        "esc": "esc", "space": "space", "enter": "enter", "tab": "tab",
        "backspace": "backspace", "delete": "delete", "insert": "insert",
        "home": "home", "end": "end", "page_up": "page up", "page_down": "page down",
        "up": "up", "down": "down", "left": "left", "right": "right",
        "caps_lock": "caps lock", "scroll_lock": "scroll lock", "num_lock": "num lock",
        "print_screen": "print screen", "pause": "pause", "menu": "menu",
    }

    def __init__(self, handler: _Handler) -> None:
        super().__init__(handler)
        from pynput import keyboard

        self._pynput = keyboard
        self._listener = None

    def start(self) -> None:
        self._listener = self._pynput.Listener(
            on_press=lambda key: self._emit(key, True),
            on_release=lambda key: self._emit(key, False),
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def suppress(self, combo: str) -> None:
        print("[hotkeys] скрывать нажатие от активного окна на этой системе нельзя")

    def _emit(self, key, is_down: bool) -> None:
        name = self._name(key)
        if name:
            self._handler(name, is_down)

    def _name(self, key) -> str:
        Key = self._pynput.Key
        if isinstance(key, Key):
            raw = key.name
            if raw in self._SPECIAL:
                return self._SPECIAL[raw]
            # f1…f20, media-клавиши: имя совпадает с записью в конфиге.
            return raw
        char = getattr(key, "char", None)
        if char:
            return char.lower()
        # Клавиша без символа (например, с зажатым Ctrl): по коду.
        vk = getattr(key, "vk", None)
        if vk is not None and 0x30 <= vk <= 0x5A:
            return chr(vk).lower()
        return ""


def _make_backend(handler: _Handler) -> _Backend:
    if sys.platform == "win32":
        return _KeyboardBackend(handler)
    return _PynputBackend(handler)
