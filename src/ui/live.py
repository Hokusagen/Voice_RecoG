"""Живой захват фона под HUD.

Однократный снимок оставляет стекло мёртвым: прокрутка под плашкой не меняет
размытие. Живой режим пересобирает стекло из свежего снимка экрана в фоновом
потоке; интерфейсный поток лишь рисует последний готовый кадр.

Чтобы окно не попадало в собственный снимок, оно исключается из захвата
(SetWindowDisplayAffinity, WDA_EXCLUDEFROMCAPTURE). Windows отказывается
исключать окна с попиксельной прозрачностью, поэтому живой HUD непрозрачен и
рисует «прозрачность» сам: подкладывает захваченный фон под пилюлю и тень.

Захват — два бэкенда по убыванию скорости:

- DXGI Desktop Duplication (bettercam), ~3 мс на регион. На гибридных
  ноутбуках, где рабочий стол сканирует интегрированная карта, а процесс
  прикреплён к дискретной, Windows запрещает дупликацию по задумке
  (DXGI_ERROR_UNSUPPORTED, KB3019314) — это лечится только выбором
  «Автовыбор» графического процессора в панели NVIDIA.
- GDI BitBlt в постоянную DIB-секцию, ~13 мс на этой машине. Стекло успевает
  обновляться ~40 раз в секунду — глазом от 60 не отличается, потому что
  содержимое под плашкой размыто.

Windows.Graphics.Capture не подходит: до Windows 11 системе нельзя запретить
рисовать жёлтую рамку вокруг захватываемого экрана.
"""

from __future__ import annotations

import ctypes
import os
import statistics
import sys
import threading
import time
from ctypes import wintypes

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from ui.liquid import MARGIN, Backdrop
from ui.theme import Material

WDA_EXCLUDEFROMCAPTURE = 0x00000011

_SRCCOPY = 0x00CC0020
_CAPTUREBLT = 0x40000000

_STATS = bool(os.environ.get("VOICETYPER_GLASS_STATS"))


def _user32():
    """Свой экземпляр user32 с сигнатурами: у ctypes.windll они общие на процесс."""
    user32 = ctypes.WinDLL("user32")
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    return user32


def exclude_from_capture(win_id: int) -> bool:
    """Прячет окно от всех систем захвата экрана — включая наш собственный.

    Побочный эффект, о котором стоит помнить: HUD не будет виден в OBS, Zoom
    и любой записи экрана.
    """
    if sys.platform != "win32":
        return False
    return bool(_user32().SetWindowDisplayAffinity(wintypes.HWND(win_id), WDA_EXCLUDEFROMCAPTURE))


def available() -> bool:
    """Возможен ли живой режим на этой системе.

    Требуется работающий WDA_EXCLUDEFROMCAPTURE (Windows 10 2004+) и экраны
    без масштабирования: захват отдаёт физические пиксели, и при dpr != 1 они
    разошлись бы с координатами Qt.
    """
    if sys.platform != "win32":
        return False
    for screen in QApplication.screens():
        if abs(screen.devicePixelRatio() - 1.0) > 1e-3:
            print("[live] экран с масштабированием — живое стекло выключено")
            return False
    user32 = _user32()
    user32.CreateWindowExW.restype = wintypes.HWND
    handle = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 1, 1, None, None, None, None)
    if not handle:
        return False
    supported = bool(user32.SetWindowDisplayAffinity(handle, WDA_EXCLUDEFROMCAPTURE))
    user32.DestroyWindow(handle)
    if not supported:
        print("[live] WDA_EXCLUDEFROMCAPTURE не поддерживается — живое стекло выключено")
    return supported


# ---------- бэкенды захвата ----------


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class _GdiGrabber:
    """BitBlt виртуального экрана в DIB-секцию, переиспользуемую между кадрами."""

    name = "gdi"

    def __init__(self) -> None:
        # Без argtypes ctypes подставляет c_int, и 64-битные хендлы GDI
        # с установленным старшим битом ломаются на переполнении.
        gdi32 = ctypes.WinDLL("gdi32")
        gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR] * 3 + [ctypes.c_void_p]
        gdi32.CreateDCW.restype = wintypes.HDC
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(_BITMAPINFO),
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        gdi32.BitBlt.argtypes = [
            wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
        ]
        gdi32.BitBlt.restype = wintypes.BOOL
        self._gdi32 = gdi32
        # DC «DISPLAY» покрывает весь виртуальный экран: координаты совпадают
        # с глобальными координатами Qt, включая мониторы левее главного.
        self._screen_dc = gdi32.CreateDCW("DISPLAY", None, None, None)
        self._mem_dc = gdi32.CreateCompatibleDC(self._screen_dc)
        self._bitmap = None
        self._view: np.ndarray | None = None
        self._size: tuple[int, int] | None = None

    def _ensure(self, width: int, height: int) -> None:
        if self._size == (width, height):
            return
        if self._bitmap:
            self._gdi32.DeleteObject(self._bitmap)
        info = _BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # отрицательная высота: строки сверху вниз
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        bits = ctypes.c_void_p()
        self._bitmap = self._gdi32.CreateDIBSection(
            None, ctypes.byref(info), 0, ctypes.byref(bits), None, 0
        )
        self._gdi32.SelectObject(self._mem_dc, self._bitmap)
        buffer = (ctypes.c_ubyte * (width * height * 4)).from_address(bits.value)
        self._view = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
        self._size = (width, height)

    def grab(self, x: int, y: int, width: int, height: int) -> np.ndarray | None:
        self._ensure(width, height)
        ok = self._gdi32.BitBlt(
            self._mem_dc, 0, 0, width, height, self._screen_dc, x, y, _SRCCOPY | _CAPTUREBLT
        )
        if not ok:
            return None
        # Копия обязательна: DIB перезаписывается следующим кадром.
        return self._view.copy()

    def close(self) -> None:
        if self._bitmap:
            self._gdi32.DeleteObject(self._bitmap)
            self._bitmap = None
        self._gdi32.DeleteDC(self._mem_dc)
        self._gdi32.DeleteDC(self._screen_dc)


def _duplication_supported() -> bool:
    """Быстрая проба DXGI-дупликации, не оставляющая недособранных объектов.

    bettercam при отказе DuplicateOutput бросает исключение из середины
    конструктора и потом сорит в stderr из __del__ — поэтому сначала пробуем
    сами тот же вызов на голых интерфейсах.
    """
    try:
        import comtypes
        from bettercam._libs.d3d11 import ID3D11Device, ID3D11DeviceContext
        from bettercam._libs.dxgi import IDXGIOutputDuplication
        from bettercam.util.io import enum_dxgi_adapters, enum_dxgi_outputs

        for adapter in enum_dxgi_adapters():
            outputs = enum_dxgi_outputs(adapter)
            if not outputs:
                continue
            levels = (ctypes.c_uint * 3)(0xB000, 0xA100, 0xA000)
            device = ctypes.POINTER(ID3D11Device)()
            context = ctypes.POINTER(ID3D11DeviceContext)()
            hr = ctypes.windll.d3d11.D3D11CreateDevice(
                adapter, 0, None, 0, ctypes.byref(levels), 3, 7,
                ctypes.byref(device), None, ctypes.byref(context),
            )
            if (hr & 0xFFFFFFFF) >= 0x80000000:
                continue
            duplication = ctypes.POINTER(IDXGIOutputDuplication)()
            try:
                outputs[0].DuplicateOutput(device, ctypes.byref(duplication))
            except comtypes.COMError:
                continue
            duplication.Release()
            return True
    except Exception:
        pass
    return False


class _DxgiGrabber:
    """DXGI Desktop Duplication через bettercam. Только главный монитор."""

    name = "dxgi"

    def __init__(self) -> None:
        import bettercam

        self._camera = bettercam.create(output_color="BGRA", max_buffer_len=2)
        screen = QApplication.primaryScreen()
        geometry = screen.geometry() if screen else QRect(0, 0, 0, 0)
        self._origin = (geometry.x(), geometry.y())
        self._bounds = (geometry.width(), geometry.height())

    def grab(self, x: int, y: int, width: int, height: int) -> np.ndarray | None:
        left = x - self._origin[0]
        top = y - self._origin[1]
        if left < 0 or top < 0 or left + width > self._bounds[0] or top + height > self._bounds[1]:
            raise RuntimeError("регион вне главного монитора")
        frame = self._camera.grab(region=(left, top, left + width, top + height))
        if frame is None:
            return None  # экран не менялся с прошлого кадра
        return np.ascontiguousarray(frame)

    def close(self) -> None:
        del self._camera


def _make_grabber():
    if _duplication_supported():
        try:
            grabber = _DxgiGrabber()
            print("[live] захват: DXGI Desktop Duplication")
            return grabber
        except Exception as exc:
            print(f"[live] DXGI не завёлся ({exc}), переходим на GDI")
    return _GdiGrabber()


# ---------- сборка кадра ----------


def build_frame(
    raw: np.ndarray,
    pill_center: tuple[float, float],
    glass_size: tuple[int, int],
    glass: Material,
) -> tuple[QImage, Backdrop, QImage | None]:
    """Из сырого снимка окна — фон для подкладки, Backdrop и готовое стекло.

    raw — BGRA-пиксели всего прямоугольника окна; пилюля задана центром в его
    координатах. Снимок для стекла вырезается с запасом MARGIN вокруг пилюли,
    так что пилюля оказывается в его центре — как того ждёт сборка.
    """
    height, width = raw.shape[:2]
    background = QImage(raw.data, width, height, width * 4, QImage.Format_RGB32).copy()

    glass_w, glass_h = glass_size
    crop_w, crop_h = glass_w + 2 * MARGIN, glass_h + 2 * MARGIN
    left = round(pill_center[0] - crop_w / 2.0)
    top = round(pill_center[1] - crop_h / 2.0)
    if left < 0 or top < 0 or left + crop_w > width or top + crop_h > height:
        return background, None, None

    crop = np.ascontiguousarray(raw[top : top + crop_h, left : left + crop_w, :3], dtype=np.float32)
    backdrop = Backdrop(crop)
    image = backdrop.build_image(glass_w, glass_h, glass)
    if image is not None:
        image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    return background, backdrop, image


class LiveEngine:
    """Фоновый поток: захват -> размытия -> стекло, свежий кадр в общем слоте."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._inputs: tuple | None = None
        self._background: QImage | None = None
        self._glass: QImage | None = None
        self._glass_size: tuple[int, int] | None = None
        self._seed_grabber: _GdiGrabber | None = None

    # -- вызывается из интерфейсного потока --

    def seed(
        self,
        window_rect: QRect,
        pill_center: tuple[float, float],
        glass_size: tuple[int, int],
        glass: Material | None,
    ) -> Backdrop | None:
        """Синхронный первый кадр до show(): окно ещё скрыто, GDI его не видит.

        Возвращает Backdrop — по его светимости выбирается материал; если
        материал уже известен, сразу собирает и стекло.
        """
        if self._seed_grabber is None:
            self._seed_grabber = _GdiGrabber()
        raw = self._seed_grabber.grab(
            window_rect.x(), window_rect.y(), window_rect.width(), window_rect.height()
        )
        if raw is None:
            return None
        if glass is None:
            height, width = raw.shape[:2]
            background = QImage(raw.data, width, height, width * 4, QImage.Format_RGB32).copy()
            crop_w, crop_h = glass_size[0] + 2 * MARGIN, glass_size[1] + 2 * MARGIN
            left = round(pill_center[0] - crop_w / 2.0)
            top = round(pill_center[1] - crop_h / 2.0)
            if left < 0 or top < 0 or left + crop_w > width or top + crop_h > height:
                backdrop = None
            else:
                crop = np.ascontiguousarray(
                    raw[top : top + crop_h, left : left + crop_w, :3], dtype=np.float32
                )
                backdrop = Backdrop(crop)
            with self._lock:
                self._background, self._glass = background, None
            return backdrop
        background, backdrop, image = build_frame(raw, pill_center, glass_size, glass)
        with self._lock:
            self._background, self._glass = background, image
            self._glass_size = glass_size
        return backdrop

    def set_inputs(
        self,
        window_rect: QRect,
        pill_center: tuple[float, float],
        glass_size: tuple[int, int],
        glass: Material,
    ) -> None:
        with self._lock:
            self._inputs = (
                (window_rect.x(), window_rect.y(), window_rect.width(), window_rect.height()),
                pill_center,
                glass_size,
                glass,
            )

    def latest(self) -> tuple[QImage | None, QImage | None, tuple[int, int] | None]:
        with self._lock:
            return self._background, self._glass, self._glass_size

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="liquid-live", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        with self._lock:
            self._inputs = None

    # -- фоновый поток --

    def _run(self) -> None:
        grabber = _make_grabber()
        last_raw: np.ndarray | None = None
        last_key = None
        stats: list[float] = []
        try:
            while not self._stop.is_set():
                with self._lock:
                    inputs = self._inputs
                if inputs is None:
                    time.sleep(0.008)
                    continue
                rect, pill_center, glass_size, glass = inputs
                key = (rect, tuple(round(c) for c in pill_center), glass_size, id(glass))

                started = time.perf_counter()
                try:
                    raw = grabber.grab(*rect)
                except Exception as exc:
                    if grabber.name == "gdi":
                        print(f"[live] захват сломался: {exc}")
                        break
                    grabber.close()
                    grabber = _GdiGrabber()
                    print(f"[live] DXGI отпал ({exc}), переходим на GDI")
                    continue

                if raw is None:
                    if last_raw is None or key == last_key:
                        # Экран и параметры не менялись — пересобирать нечего.
                        time.sleep(0.004)
                        continue
                    raw = last_raw
                elif raw.shape[0] != rect[3] or raw.shape[1] != rect[2]:
                    continue
                else:
                    last_raw = raw

                background, _backdrop, image = build_frame(raw, pill_center, glass_size, glass)
                last_key = key
                with self._lock:
                    self._background = background
                    if image is not None:
                        self._glass = image
                        self._glass_size = glass_size

                elapsed = time.perf_counter() - started
                if _STATS:
                    stats.append(elapsed * 1000)
                    if len(stats) >= 120:
                        print(
                            f"[live] кадр: медиана {statistics.median(stats):.1f} мс, "
                            f"max {max(stats):.1f} мс, захват {grabber.name}"
                        )
                        stats.clear()
                # Быстрее экрана обновляться незачем.
                time.sleep(max(0.0, 1.0 / 60.0 - elapsed))
        finally:
            grabber.close()
