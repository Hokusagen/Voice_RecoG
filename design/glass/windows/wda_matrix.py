"""Матрица: какие виды окон принимают WDA_EXCLUDEFROMCAPTURE и пропадают из GDI-захвата.

Для каждого варианта: окно с пурпурной серединой -> снимок GDI до исключения ->
SetWindowDisplayAffinity -> снимок с CAPTUREBLT и без. Пурпур в снимке = окно видно захвату.
"""
from __future__ import annotations

import ctypes
import sys
import time
import uuid
from ctypes import wintypes, byref, c_void_p, POINTER

import numpy as np

HOLD = False

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32")
user32.SetProcessDpiAwarenessContext.argtypes = [c_void_p]
user32.SetProcessDpiAwarenessContext(c_void_p(-4))

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, POINTER(wintypes.DWORD)]
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.FillRect.argtypes = [wintypes.HDC, POINTER(wintypes.RECT), wintypes.HBRUSH]
user32.BeginPaint.argtypes = [wintypes.HWND, c_void_p]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, c_void_p]
user32.PeekMessageW.argtypes = [POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [POINTER(wintypes.MSG)]
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, POINTER(wintypes.POINT), POINTER(wintypes.SIZE),
                                       wintypes.HDC, POINTER(wintypes.POINT), wintypes.DWORD, c_void_p, wintypes.DWORD]
gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR] * 3 + [c_void_p]
gdi32.CreateDCW.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
HINST = kernel32.GetModuleHandleW(None)

WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x8, 0x80, 0x08000000
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOREDIRECTIONBITMAP = 0x80000, 0x20, 0x00200000
WDA_EXCLUDEFROMCAPTURE = 0x11
X, Y, W, H = 240, 240, 400, 200
INNER = (100, 50, 300, 150)  # непрозрачная пурпурная середина
MAGENTA = 0x00FF00FF  # COLORREF: 0x00BBGGRR
KEY_GREEN = 0x0000FF00


class RECT(wintypes.RECT):
    pass


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


PAINT_MODE: dict[int, str] = {}
_magenta = gdi32.CreateSolidBrush(MAGENTA)
_green = gdi32.CreateSolidBrush(KEY_GREEN)


@WNDPROC
def wndproc(hwnd, msg, wparam, lparam):
    if msg == 0x000F:  # WM_PAINT
        mode = PAINT_MODE.get(hwnd)
        if mode in ("opaque", "lwa_alpha", "colorkey"):
            ps = PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, byref(ps))
            if mode == "colorkey":
                user32.FillRect(hdc, byref(RECT(0, 0, W, H)), _green)
            else:
                user32.FillRect(hdc, byref(RECT(0, 0, W, H)), _magenta)
            user32.FillRect(hdc, byref(RECT(*INNER)), _magenta)
            user32.EndPaint(hwnd, byref(ps))
            return 0
    if msg == 0x0014:  # WM_ERASEBKGND
        return 1
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


user32.RegisterClassExW.argtypes = [POINTER(WNDCLASSEXW)]
user32.RegisterClassExW(byref(WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=wndproc,
                                          hInstance=HINST, lpszClassName="WdaMatrix")))


def pump(seconds: float) -> None:
    end = time.perf_counter() + seconds
    msg = wintypes.MSG()
    while time.perf_counter() < end:
        while user32.PeekMessageW(byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))
        time.sleep(0.005)


class BMIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


gdi32.CreateDIBSection.argtypes = [wintypes.HDC, POINTER(BMIH), wintypes.UINT, POINTER(c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP


def dib(width, height):
    info = BMIH(biSize=ctypes.sizeof(BMIH), biWidth=width, biHeight=-height, biPlanes=1, biBitCount=32)
    bits = c_void_p()
    bmp = gdi32.CreateDIBSection(None, byref(info), 0, byref(bits), None, 0)
    arr = np.frombuffer((ctypes.c_ubyte * (width * height * 4)).from_address(bits.value), dtype=np.uint8).reshape(height, width, 4)
    return bmp, arr


def grab(captureblt: bool) -> np.ndarray:
    screen = gdi32.CreateDCW("DISPLAY", None, None, None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp, arr = dib(W, H)
    old = gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, W, H, screen, X, Y, 0x00CC0020 | (0x40000000 if captureblt else 0))
    out = arr.copy()
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    gdi32.DeleteDC(screen)
    return out


def magenta_share(img: np.ndarray) -> float:
    x0, y0, x1, y1 = INNER
    part = img[y0:y1, x0:x1].astype(int)  # BGRA
    hit = (part[..., 2] > 235) & (part[..., 1] < 25) & (part[..., 0] > 235)
    return float(hit.mean())


# ---------- содержимое без перенаправления ----------

def guid(text):
    class GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]
    u = uuid.UUID(text)
    g = GUID(u.fields[0], u.fields[1], u.fields[2])
    g.d[:] = list(u.bytes[8:])
    return g


def vcall(obj, index, restype, *args, argtypes=()):
    vtbl = ctypes.cast(ctypes.cast(obj, POINTER(c_void_p))[0], POINTER(c_void_p))
    fn = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[index])
    return fn(obj, *args)


KEEP = []


def dcomp_swapchain(hwnd, premultiplied=True):
    """D3D11 + свопчейн для композиции (FLIP_SEQUENTIAL, B8G8R8A8, premultiplied) + DirectComposition."""
    d3d11 = ctypes.WinDLL("d3d11")
    dev, ctx = c_void_p(), c_void_p()
    fl = ctypes.c_uint()
    hr = d3d11.D3D11CreateDevice(None, 1, None, 0x20, None, 0, 7, byref(dev), byref(fl), byref(ctx))
    assert hr == 0, hex(hr & 0xFFFFFFFF)
    dxgi_dev = c_void_p()
    vcall(dev, 0, ctypes.HRESULT, byref(guid("54ec77fa-1377-44e6-8c32-88fd5f44c84c")), byref(dxgi_dev), argtypes=(c_void_p, c_void_p))
    factory = c_void_p()
    ctypes.WinDLL("dxgi").CreateDXGIFactory2(0, byref(guid("50c83a1c-e072-4c48-87b0-3630fa36a6d0")), byref(factory))

    class DESC1(ctypes.Structure):
        _fields_ = [("Width", ctypes.c_uint), ("Height", ctypes.c_uint), ("Format", ctypes.c_int), ("Stereo", wintypes.BOOL),
                    ("Count", ctypes.c_uint), ("Quality", ctypes.c_uint), ("BufferUsage", ctypes.c_uint),
                    ("BufferCount", ctypes.c_uint), ("Scaling", ctypes.c_int), ("SwapEffect", ctypes.c_int),
                    ("AlphaMode", ctypes.c_int), ("Flags", ctypes.c_uint)]
    desc = DESC1(W, H, 87, 0, 1, 0, 0x20, 2, 0, 3, 1 if premultiplied else 3, 0)
    swap = c_void_p()
    hr = vcall(factory, 24, ctypes.HRESULT, dev, byref(desc), None, byref(swap), argtypes=(c_void_p, c_void_p, c_void_p, c_void_p))
    assert hr == 0, hex(hr & 0xFFFFFFFF)
    tex = c_void_p()
    vcall(swap, 9, ctypes.HRESULT, 0, byref(guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c")), byref(tex), argtypes=(ctypes.c_uint, c_void_p, c_void_p))
    # Кадр: рамка 0.5 альфы, середина непрозрачный пурпур, между — полностью прозрачно.
    img = np.zeros((H, W, 4), np.uint8)
    img[:20, :] = (128, 0, 128, 128)
    x0, y0, x1, y1 = INNER
    img[y0:y1, x0:x1] = (255, 0, 255, 255)
    vcall(ctx, 48, None, tex, 0, None, img.ctypes.data, W * 4, 0,
          argtypes=(c_void_p, ctypes.c_uint, c_void_p, c_void_p, ctypes.c_uint, ctypes.c_uint))
    hr = vcall(swap, 8, ctypes.HRESULT, 1, 0, argtypes=(ctypes.c_uint, ctypes.c_uint))
    dcomp = ctypes.WinDLL("dcomp")
    ddev = c_void_p()
    hr = dcomp.DCompositionCreateDevice(dxgi_dev, byref(guid("C37EA93A-E7AA-450D-B16F-9746CB0407F3")), byref(ddev))
    assert hr == 0, hex(hr & 0xFFFFFFFF)
    target, visual = c_void_p(), c_void_p()
    assert vcall(ddev, 6, ctypes.HRESULT, hwnd, 1, byref(target), argtypes=(wintypes.HWND, wintypes.BOOL, c_void_p)) == 0
    assert vcall(ddev, 7, ctypes.HRESULT, byref(visual), argtypes=(c_void_p,)) == 0
    assert vcall(visual, 15, ctypes.HRESULT, swap, argtypes=(c_void_p,)) == 0
    assert vcall(target, 3, ctypes.HRESULT, visual, argtypes=(c_void_p,)) == 0
    assert vcall(ddev, 3, ctypes.HRESULT) == 0
    KEEP.extend([dev, ctx, dxgi_dev, factory, swap, tex, ddev, target, visual])


_WINRT = {}


def winui_composition(hwnd):
    """Windows.UI.Composition: DesktopWindowTarget, пурпурный спрайт в середине, полупрозрачная полоса сверху."""
    if not _WINRT:
        class DQO(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("threadType", ctypes.c_int), ("apartmentType", ctypes.c_int)]
        ctypes.windll.ole32.CoInitializeEx(None, 2)
        ctrl = c_void_p()
        ctypes.WinDLL("CoreMessaging").CreateDispatcherQueueController(DQO(ctypes.sizeof(DQO), 2, 1), byref(ctrl))
        from winrt.windows.ui.composition import Compositor
        _WINRT["ctrl"] = ctrl
        _WINRT["comp"] = Compositor()
    from winrt.windows.foundation.numerics import Vector2, Vector3
    from winrt.windows.ui import Color
    from winrt.windows.ui.composition.interop import create_desktop_window_target
    comp = _WINRT["comp"]
    target = create_desktop_window_target(comp, hwnd, is_topmost=True)
    root = comp.create_container_visual()
    root.size = Vector2(W, H)
    target.root = root
    band = comp.create_sprite_visual()
    band.size = Vector2(W, 20)
    band.brush = comp.create_color_brush_with_color(Color(a=128, r=255, g=0, b=255))
    root.children.insert_at_top(band)
    s = comp.create_sprite_visual()
    x0, y0, x1, y1 = INNER
    s.size = Vector2(x1 - x0, y1 - y0)
    s.offset = Vector3(x0, y0, 0)
    s.brush = comp.create_color_brush_with_color(Color(a=255, r=255, g=0, b=255))
    root.children.insert_at_top(s)
    KEEP.extend([target, root, band, s])


def ulw_content(hwnd):
    """UpdateLayeredWindow: попиксельная альфа, как у Qt WA_TranslucentBackground."""
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp, arr = dib(W, H)
    arr[:] = 0
    arr[:20, :] = (128, 0, 128, 128)
    x0, y0, x1, y1 = INNER
    arr[y0:y1, x0:x1] = (255, 0, 255, 255)
    gdi32.SelectObject(mem, bmp)
    blend = (ctypes.c_ubyte * 4)(0, 0, 255, 1)
    ok = user32.UpdateLayeredWindow(hwnd, screen, byref(wintypes.POINT(X, Y)), byref(wintypes.SIZE(W, H)),
                                    mem, byref(wintypes.POINT(0, 0)), 0, blend, 2)
    user32.ReleaseDC(None, screen)
    return ok


VARIANTS = [
    ("A opaque WS_POPUP (GDI)", 0, "opaque"),
    ("B layered + UpdateLayeredWindow (per-pixel alpha)", WS_EX_LAYERED, "ulw"),
    ("C layered + SetLayeredWindowAttributes(LWA_ALPHA 255)", WS_EX_LAYERED, "lwa_alpha"),
    ("D layered + LWA_COLORKEY (binary cutout)", WS_EX_LAYERED, "colorkey"),
    ("E NOREDIRECTIONBITMAP + Windows.UI.Composition", WS_EX_NOREDIRECTIONBITMAP, "winui"),
    ("F E + LAYERED(LWA_ALPHA 255) + TRANSPARENT", WS_EX_NOREDIRECTIONBITMAP | WS_EX_LAYERED | WS_EX_TRANSPARENT, "winui_layered"),
    ("G NOREDIRECTIONBITMAP + DComp swapchain PREMULTIPLIED", WS_EX_NOREDIRECTIONBITMAP, "dcomp"),
    ("H G + LAYERED(LWA_ALPHA 255) + TRANSPARENT", WS_EX_NOREDIRECTIONBITMAP | WS_EX_LAYERED | WS_EX_TRANSPARENT, "dcomp_layered"),
]


def run(name, ex, mode):
    ex |= WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    hwnd = user32.CreateWindowExW(ex, "WdaMatrix", name, WS_POPUP, X, Y, W, H, None, None, HINST, None)
    PAINT_MODE[hwnd] = mode
    if mode in ("lwa_alpha", "winui_layered", "dcomp_layered"):
        user32.SetLayeredWindowAttributes(hwnd, 0, 255, 2)
    if mode == "colorkey":
        user32.SetLayeredWindowAttributes(hwnd, KEY_GREEN, 0, 1)
    if mode == "ulw":
        ulw_content(hwnd)
    if mode.startswith("winui"):
        winui_composition(hwnd)
    if mode.startswith("dcomp"):
        dcomp_swapchain(hwnd)
    user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
    pump(0.6)
    before = magenta_share(grab(True))
    ok = user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    err = ctypes.get_last_error() if not ok else 0
    aff = wintypes.DWORD()
    user32.GetWindowDisplayAffinity(hwnd, byref(aff))
    pump(0.6)
    if HOLD:
        print(f"{name}: окно исключено из захвата и держится 8 с — оно должно быть ВИДНО на мониторе")
        pump(8.0)
    after_blt = magenta_share(grab(True))
    after_noblt = magenta_share(grab(False))
    user32.DestroyWindow(hwnd)
    pump(0.2)
    print(f"{name:58s} | before {before:4.2f} | SetWDA ok={bool(ok)} err={err} aff=0x{aff.value:02x} "
          f"| after CAPTUREBLT {after_blt:4.2f} | after plain {after_noblt:4.2f}")


HOLD = "--hold" in sys.argv

if __name__ == "__main__":
    only = [a for a in sys.argv[1:] if not a.startswith("--")] or None
    print("Доля пурпура в непрозрачной середине окна в GDI-снимке (1.0 = окно видно захвату)")
    for name, ex, mode in VARIANTS:
        if only and name[0] not in only:
            continue
        try:
            run(name, ex, mode)
        except Exception as exc:  # noqa: BLE001
            print(f"{name:58s} | ОШИБКА {exc!r}")
