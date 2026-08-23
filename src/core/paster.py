"""Вставка текста в активное окно через буфер обмена.

Буфер обмена — общий ресурс: если просто положить туда распознанный текст, у
пользователя пропадёт всё, что он копировал до диктовки. Здесь прежнее
содержимое запоминается и возвращается обратно, но только если за время вставки
его никто не перезаписал.
"""

from __future__ import annotations

import threading
import time

import keyboard
import win32clipboard
import win32con

_MODIFIERS = ("ctrl", "alt", "shift", "windows", "win")


class ClipboardError(RuntimeError):
    """Не удалось получить доступ к буферу обмена."""


def _open_clipboard(attempts: int = 8, delay: float = 0.02) -> None:
    """Буфер обмена монопольный: другое приложение могло держать его открытым."""
    last: Exception | None = None
    for _ in range(attempts):
        try:
            win32clipboard.OpenClipboard()
            return
        except Exception as exc:
            last = exc
            time.sleep(delay)
    raise ClipboardError(f"буфер обмена занят: {last}")


def read_text() -> str | None:
    """Текст из буфера обмена; None — если там не текст (картинка, файлы)."""
    _open_clipboard()
    try:
        if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return None
        return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
    except Exception:
        return None
    finally:
        win32clipboard.CloseClipboard()


def write_text(text: str) -> None:
    _open_clipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()


def _release_modifiers(hotkey: str) -> None:
    """Отпускает модификаторы, которые пользователь ещё физически держит.

    Если горячая клавиша — например ctrl+alt+F8, то в момент вставки Ctrl уже
    нажат, и ctrl+v превратится в ctrl+ctrl+v или вовсе в другое сочетание.
    """
    lowered = hotkey.lower()
    for name in _MODIFIERS:
        if name in lowered:
            try:
                keyboard.release(name)
            except Exception:
                pass


class Paster:
    def __init__(self, cfg) -> None:
        self.cfg = cfg

    def paste(self, text: str, hotkey: str = "") -> None:
        """Кладёт текст в буфер, шлёт Ctrl+V и возвращает буфер как было."""
        if not text:
            return

        payload = text + " " if self.cfg.trailing_space else text

        previous: str | None = None
        had_text = False
        if self.cfg.restore_clipboard:
            previous = read_text()
            had_text = previous is not None

        write_text(payload)
        # Некоторые приложения читают буфер асинхронно и не успевают увидеть
        # свежие данные, если Ctrl+V прилетает в ту же миллисекунду.
        time.sleep(self.cfg.paste_delay_ms / 1000)

        if hotkey:
            _release_modifiers(hotkey)
        keyboard.send("ctrl+v")

        if had_text:
            # Возврат буфера ждёт треть секунды, пока приложение дочитает
            # вставку. Держать на этом конвейер незачем — иначе «Готово»
            # показалось бы позже самой вставки.
            threading.Thread(
                target=self._restore_later, args=(previous, payload), daemon=True
            ).start()

    def _restore_later(self, previous: str, payload: str) -> None:
        time.sleep(self.cfg.restore_delay_ms / 1000)
        try:
            # Если пользователь успел скопировать что-то своё, откат затёр бы
            # его копию — тогда лучше ничего не трогать.
            if read_text() == payload:
                write_text(previous)
        except ClipboardError as exc:
            print(f"[paster] не удалось вернуть буфер обмена: {exc}")
