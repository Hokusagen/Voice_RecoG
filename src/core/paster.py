"""Вставка текста в активное окно через буфер обмена.

Буфер обмена — общий ресурс: если просто положить туда распознанный текст, у
пользователя пропадёт всё, что он копировал до диктовки. Здесь прежнее
содержимое запоминается и возвращается обратно, но только если за время вставки
его никто не перезаписал.

Буфер и нажатие «вставить» зависят от системы: на Windows это win32clipboard и
Ctrl+V через keyboard, на macOS — pbcopy/pbpaste и Cmd+V через pynput. Обе
пары безопасно звать из рабочего потока конвейера, в отличие от QClipboard,
который живёт только в потоке интерфейса.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time

_MODIFIERS = ("ctrl", "alt", "shift", "windows", "win", "cmd")


class ClipboardError(RuntimeError):
    """Не удалось получить доступ к буферу обмена."""


# ---------- буфер обмена ----------

if sys.platform == "win32":
    import win32clipboard
    import win32con

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

elif sys.platform == "darwin":

    def read_text() -> str | None:
        try:
            result = subprocess.run(["pbpaste"], capture_output=True, timeout=2.0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ClipboardError(f"pbpaste не ответил: {exc}") from exc
        if result.returncode != 0:
            return None
        try:
            return result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def write_text(text: str) -> None:
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, timeout=2.0)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ClipboardError(f"pbcopy не принял текст: {exc}") from exc

else:

    def _xclip(args: list[str], data: bytes | None = None) -> bytes:
        for tool in (["xclip", "-selection", "clipboard"] + args, ["xsel", "--clipboard"] + args):
            try:
                result = subprocess.run(tool, input=data, capture_output=True, timeout=2.0)
            except OSError:
                continue
            if result.returncode == 0:
                return result.stdout
        raise ClipboardError("нужен xclip или xsel")

    def read_text() -> str | None:
        try:
            return _xclip(["-o"]).decode("utf-8")
        except UnicodeDecodeError:
            return None

    def write_text(text: str) -> None:
        _xclip(["-i"], text.encode("utf-8"))


# ---------- нажатие «вставить» ----------

if sys.platform == "win32":
    import keyboard

    def _release(name: str) -> None:
        keyboard.release(name)

    def _send_paste() -> None:
        keyboard.send("ctrl+v")

else:
    from pynput.keyboard import Controller, Key

    _controller = Controller()
    _KEYS = {
        "ctrl": Key.ctrl, "alt": Key.alt, "shift": Key.shift,
        "cmd": Key.cmd, "windows": Key.cmd, "win": Key.cmd,
    }

    def _release(name: str) -> None:
        key = _KEYS.get(name)
        if key is not None:
            _controller.release(key)

    def _send_paste() -> None:
        modifier = Key.cmd if sys.platform == "darwin" else Key.ctrl
        with _controller.pressed(modifier):
            _controller.press("v")
            _controller.release("v")


def _release_modifiers(hotkey: str) -> None:
    """Отпускает модификаторы, которые пользователь ещё физически держит.

    Если горячая клавиша — например ctrl+alt+F8, то в момент вставки Ctrl уже
    нажат, и ctrl+v превратится в ctrl+ctrl+v или вовсе в другое сочетание.
    """
    lowered = hotkey.lower()
    for name in _MODIFIERS:
        if name in lowered:
            try:
                _release(name)
            except Exception:
                pass


class Paster:
    def __init__(self, cfg) -> None:
        self.cfg = cfg

    def paste(self, text: str, hotkey: str = "") -> None:
        """Кладёт текст в буфер, шлёт «вставить» и возвращает буфер как было."""
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
        _send_paste()

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
