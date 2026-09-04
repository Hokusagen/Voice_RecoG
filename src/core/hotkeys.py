"""Глобальные горячие клавиши.

Прошлая версия опрашивала keyboard.is_pressed в цикле каждые 20 мс: это и грело
процессор впустую, и теряло короткие нажатия между итерациями. Здесь стоит
низкоуровневый хук, который сам будит нас на событии клавиатуры.

Состояние клавиш считается по самим событиям, а не через keyboard.is_pressed:
хуки библиотеки вызываются из очереди, и к моменту обработки нажатия клавишу
уже могли отпустить — короткий тап в режиме «нажать / нажать» просто пропал бы.

Хук живёт в собственном потоке библиотеки keyboard, поэтому наружу состояние
уходит сигналами Qt: доставка в поток GUI — забота очереди событий.
"""

from __future__ import annotations

import keyboard
from PySide6.QtCore import QObject, Signal

from config import HotkeysConfig

#: Действия в порядке убывания специфичности: ctrl+f8 должен побеждать f8,
#: иначе одно нажатие поднимет сразу оба.
_ACTIONS = ("record_raw", "record_alt", "record")


class HotkeyListener(QObject):
    pressed = Signal(str)
    released = Signal(str)
    cancelled = Signal()

    def __init__(self, cfg: HotkeysConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self._enabled = True
        self._active: str | None = None
        self._hook = None
        self._blocked_key: str | None = None

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
            name: frozenset(part.strip() for part in combo.split("+") if part.strip())
            for name, combo in combos.items()
        }
        # Сначала сочетания из большего числа клавиш.
        self._order = sorted(self._keys, key=lambda name: -len(self._keys[name]))

        self._cancel_key = (self.cfg.cancel or "").strip().lower()
        self._watched = {key for keys in self._keys.values() for key in keys}
        if self._cancel_key:
            self._watched.add(self._cancel_key)

        self._down.clear()
        self._hook = keyboard.hook(self._on_event)
        self._apply_suppression()

    def stop(self) -> None:
        if self._hook is not None:
            try:
                keyboard.unhook(self._hook)
            except (KeyError, ValueError):
                pass
            self._hook = None
        self._unblock()

    def _apply_suppression(self) -> None:
        if not self.cfg.suppress:
            return
        combo = self.cfg.record.strip().lower()
        if "+" in combo:
            print("[hotkeys] скрывать нажатие можно только для одиночной клавиши")
            return
        try:
            keyboard.block_key(combo)
            self._blocked_key = combo
        except (ValueError, KeyError) as exc:
            print(f"[hotkeys] не удалось перехватить {combo}: {exc}")

    def _unblock(self) -> None:
        if self._blocked_key is None:
            return
        try:
            keyboard.unblock_key(self._blocked_key)
        except (KeyError, ValueError):
            pass
        self._blocked_key = None

    # ---------- состояние ----------

    def set_enabled(self, enabled: bool) -> None:
        """Пауза: хук остаётся, но события не превращаются в действия."""
        self._enabled = enabled
        if not enabled and self._active is not None:
            name, self._active = self._active, None
            self.released.emit(name)

    # ---------- обработка событий ----------

    def _on_event(self, event) -> None:
        name = (event.name or "").lower()
        if name not in self._watched:
            return

        is_down = event.event_type == keyboard.KEY_DOWN
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
