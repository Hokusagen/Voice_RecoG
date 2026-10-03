"""Проба: стекло Линзы без видимого отставания захвата.

Захват экрана всегда отстаёт от настоящего стола на кадр-два: GDI отдаёт
последний собранный кадр, а наш собирается следующим. Отставание видно там,
где содержимое под стеклом продолжает то, что вокруг: при прокрутке строки
в середине плашки «едут» позже строк снаружи.

Гибрид делит стекло по этому признаку:

- середину рисует системный композитор — BackdropBrush, размытие σ 2.4 и тон
  Apple (in·1.015 + 0.086) в том же кадре, что и весь экран, отставать нечему;
- кромку рисует свой шейдер по захвату: у кромки выборка идёт внутрь на
  десятки пикселей, фон там перевёрнут и сжат, продолжения снаружи у него нет,
  и запоздание на кадр глазу не за что зацепить. Ближе к середине, где
  смещение мало, шейдер плавно уступает живой середине.

Окно без поверхности перенаправления: снаружи пилюли настоящий стол, а не
его копия, поэтому кольца вокруг плашки нет. Из захвата окно исключено, иначе
шейдер видел бы сам себя.

Режимы для сравнения при прокрутке под плашкой (переключатель в углу экрана):
гибрид; весь захват — как нынешний HUD, всё стекло из снимка; без линзы —
только живая середина и блик.

    venv\\Scripts\\python.exe design\\glass\\windows\\hybrid_probe.py
    ... hybrid_probe.py --look out.png   — снимок плашки во всех режимах и выход
    ... hybrid_probe.py --measure        — замер запаздывания живой середины

Для снимка окно не исключается из захвата, а фон снимается один раз до показа:
иначе на снимке экрана плашки просто нет.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import POINTER, Structure, byref, c_float, c_uint, c_void_p, sizeof
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QButtonGroup, QLabel, QRadioButton, QVBoxLayout, QWidget

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

LOOK = sys.argv[sys.argv.index("--look") + 1] if "--look" in sys.argv else None
MEASURE = "--measure" in sys.argv
# Снимок и замер видят плашку на снимке экрана: окно не исключается из захвата,
# а шейдер берёт фон из одного снимка до показа, чтобы не видеть сам себя.
OFFLINE = LOOK is not None or MEASURE

app = QApplication(sys.argv)

from winrt.windows.foundation.numerics import Vector2, Vector3  # noqa: E402
from winrt.windows.ui.composition import Compositor  # noqa: E402
from winrt.windows.ui.composition.interop import create_desktop_window_target  # noqa: E402

import comp_blur  # noqa: E402
from comp_blur import GUID, qi, release, vcall  # noqa: E402
from ui.live import _GdiGrabber  # noqa: E402

# ---------- геометрия ----------

PILL_W, PILL_H = 420, 56
# Запас под тень: 0.035·exp(−sd/30) меньше 1/255 уже на ~60 px.
MARGIN = 64
WIN_W, WIN_H = PILL_W + 2 * MARGIN, PILL_H + 2 * MARGIN
_area = QGuiApplication.primaryScreen().availableGeometry()
if abs(QGuiApplication.primaryScreen().devicePixelRatio() - 1.0) > 1e-3:
    print("[probe] экран с масштабированием: координаты разойдутся, проба рассчитана на 100%")
WIN_X = _area.center().x() - WIN_W // 2
WIN_Y = _area.bottom() - 96 - PILL_H // 2 - WIN_H // 2  # центр пилюли там же, где у нынешней плашки

# ---------- окно ----------

user32 = ctypes.WinDLL("user32", use_last_error=True)


class _DQO(Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("threadType", ctypes.c_int), ("apartmentType", ctypes.c_int)]


_dispatcher = c_void_p()
ctypes.WinDLL("CoreMessaging").CreateDispatcherQueueController(
    _DQO(sizeof(_DQO), 2, 0), byref(_dispatcher)  # текущий поток, COM уже поднял Qt
)

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t


@WNDPROC
def _wndproc(hwnd, msg, wparam, lparam):
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


class _WNDCLASSEXW(Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
    ]


_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_hinst = _kernel32.GetModuleHandleW(None)
user32.RegisterClassExW.argtypes = [POINTER(_WNDCLASSEXW)]
user32.RegisterClassExW(byref(_WNDCLASSEXW(cbSize=sizeof(_WNDCLASSEXW), lpfnWndProc=_wndproc,
                                           hInstance=_hinst, lpszClassName="VoiceTyperHybridProbe")))
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

# NOREDIRECTIONBITMAP | TOPMOST | TOOLWINDOW | NOACTIVATE | TRANSPARENT | LAYERED:
# всё рисует композиция, поверх всех, без фокуса и сквозное для мыши — как HUD.
_EX = 0x00200000 | 0x8 | 0x80 | 0x08000000 | 0x20 | 0x00080000
hwnd = user32.CreateWindowExW(_EX, "VoiceTyperHybridProbe", "hybrid", 0x80000000,
                              WIN_X, WIN_Y, WIN_W, WIN_H, None, None, _hinst, None)
user32.SetLayeredWindowAttributes(hwnd, 0, 255, 2)
if not OFFLINE and not user32.SetWindowDisplayAffinity(hwnd, 0x11):
    print(f"[probe] окно не исключилось из захвата (ошибка {ctypes.get_last_error()}): шейдер увидит сам себя")

# ---------- D3D11 и свопчейн для композиции ----------


def _guid(text: str) -> GUID:
    return GUID.of(text)


IID_IDXGIDevice = _guid("54ec77fa-1377-44e6-8c32-88fd5f44c84c")
IID_IDXGIFactory2 = _guid("50c83a1c-e072-4c48-87b0-3630fa36a6d0")
IID_ID3D11Texture2D = _guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c")
IID_ICompositorInterop = _guid("25297D5C-3AD4-4C9C-B5CF-E36A38512330")
IID_ICompositionSurfaceBrush = _guid("AD016D79-1E4C-4C0D-9C29-83338C87C162")
CLSID_D2D1ColorMatrix = _guid("921F03D6-641C-47DF-852D-B4BB6153AE11")

DXGI_FORMAT_B8G8R8A8_UNORM = 87


class DXGI_SWAP_CHAIN_DESC1(Structure):
    _fields_ = [("Width", c_uint), ("Height", c_uint), ("Format", ctypes.c_int), ("Stereo", wintypes.BOOL),
                ("Count", c_uint), ("Quality", c_uint), ("BufferUsage", c_uint), ("BufferCount", c_uint),
                ("Scaling", ctypes.c_int), ("SwapEffect", ctypes.c_int), ("AlphaMode", ctypes.c_int),
                ("Flags", c_uint)]


class D3D11_TEXTURE2D_DESC(Structure):
    _fields_ = [("Width", c_uint), ("Height", c_uint), ("MipLevels", c_uint), ("ArraySize", c_uint),
                ("Format", ctypes.c_int), ("Count", c_uint), ("Quality", c_uint), ("Usage", ctypes.c_int),
                ("BindFlags", c_uint), ("CPUAccessFlags", c_uint), ("MiscFlags", c_uint)]


class D3D11_BUFFER_DESC(Structure):
    _fields_ = [("ByteWidth", c_uint), ("Usage", ctypes.c_int), ("BindFlags", c_uint),
                ("CPUAccessFlags", c_uint), ("MiscFlags", c_uint), ("StructureByteStride", c_uint)]


class D3D11_SAMPLER_DESC(Structure):
    _fields_ = [("Filter", ctypes.c_int), ("AddressU", ctypes.c_int), ("AddressV", ctypes.c_int),
                ("AddressW", ctypes.c_int), ("MipLODBias", c_float), ("MaxAnisotropy", c_uint),
                ("ComparisonFunc", ctypes.c_int), ("BorderColor", c_float * 4), ("MinLOD", c_float),
                ("MaxLOD", c_float)]


class D3D11_VIEWPORT(Structure):
    _fields_ = [("TopLeftX", c_float), ("TopLeftY", c_float), ("Width", c_float), ("Height", c_float),
                ("MinDepth", c_float), ("MaxDepth", c_float)]


def _check(hr: int, what: str) -> None:
    if hr != 0:
        raise OSError(f"{what}: {hr & 0xFFFFFFFF:#010x}")


_HR = ctypes.HRESULT
_P = c_void_p
_PP = POINTER(c_void_p)

d3d11 = ctypes.WinDLL("d3d11")
device, context = c_void_p(), c_void_p()
_feature = c_uint()
# BGRA_SUPPORT: без него свопчейн B8G8R8A8 для композиции не создаётся.
_check(d3d11.D3D11CreateDevice(None, 1, None, 0x20, None, 0, 7, byref(device), byref(_feature), byref(context)),
       "D3D11CreateDevice")
device, context = device.value, context.value

_factory = c_void_p()
_check(ctypes.WinDLL("dxgi").CreateDXGIFactory2(0, byref(IID_IDXGIFactory2), byref(_factory)), "CreateDXGIFactory2")
_desc = DXGI_SWAP_CHAIN_DESC1(WIN_W, WIN_H, DXGI_FORMAT_B8G8R8A8_UNORM, 0, 1, 0, 0x20, 2, 0, 3, 1, 0)
swapchain = c_void_p()
_check(vcall(_factory.value, 24, _HR, [_P, POINTER(DXGI_SWAP_CHAIN_DESC1), _P, _PP],
             device, byref(_desc), None, byref(swapchain)), "CreateSwapChainForComposition")
swapchain = swapchain.value

_backbuffer = c_void_p()
_check(vcall(swapchain, 9, _HR, [c_uint, POINTER(GUID), _PP], 0, byref(IID_ID3D11Texture2D), byref(_backbuffer)),
       "GetBuffer")
# В D3D11 с моделью flip нулевой буфер — всегда текущий задний: вид создаётся один раз.
rtv = c_void_p()
_check(vcall(device, 9, _HR, [_P, _P, _PP], _backbuffer.value, None, byref(rtv)), "CreateRenderTargetView")

# Снимок фона под окном — текстура того же размера, что и окно.
_tex_desc = D3D11_TEXTURE2D_DESC(WIN_W, WIN_H, 1, 1, DXGI_FORMAT_B8G8R8A8_UNORM, 1, 0, 0, 0x8, 0, 0)
scene_tex = c_void_p()
_check(vcall(device, 5, _HR, [POINTER(D3D11_TEXTURE2D_DESC), _P, _PP], byref(_tex_desc), None,
             byref(scene_tex)), "CreateTexture2D")
scene_tex = scene_tex.value
scene_srv = c_void_p()
_check(vcall(device, 7, _HR, [_P, _P, _PP], scene_tex, None, byref(scene_srv)), "CreateShaderResourceView")

_sampler_desc = D3D11_SAMPLER_DESC(0x15, 3, 3, 3, 0.0, 1, 8, (c_float * 4)(0, 0, 0, 0), 0.0, 3.4e38)
sampler = c_void_p()
_check(vcall(device, 23, _HR, [POINTER(D3D11_SAMPLER_DESC), _PP], byref(_sampler_desc), byref(sampler)),
       "CreateSamplerState")


class Params(Structure):
    _fields_ = [("res", c_float * 2), ("center", c_float * 2), ("size", c_float * 2), ("mat", c_float),
                ("mode", c_float), ("time", c_float), ("refraction", c_float), ("pad", c_float * 2)]


_cb_desc = D3D11_BUFFER_DESC(sizeof(Params), 0, 0x4, 0, 0, 0)
cbuffer = c_void_p()
_check(vcall(device, 3, _HR, [POINTER(D3D11_BUFFER_DESC), _P, _PP], byref(_cb_desc), None, byref(cbuffer)),
       "CreateBuffer")

# ---------- шейдер ----------

# Перенос liquidGlass из harness.js (GLSL ES) на HLSL без изменения чисел.
HLSL = r"""
Texture2D uScene : register(t0);
SamplerState uSamp : register(s0);
cbuffer Params : register(b0) {
    float2 uRes; float2 uCenter; float2 uSize;
    float uMat; float uMode; float uTime; float uRefraction; float2 uPad;
};

float4 vs_main(uint id : SV_VertexID) : SV_Position {
    float2 uv = float2((id << 1) & 2, id & 2);
    return float4(uv * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
}

float3 sceneAt(float2 p) { return uScene.SampleLevel(uSamp, p / uRes, 0.0).rgb; }
// Размытие: 12 выборок по золотой спирали, как sceneBlur лаборатории.
float3 sceneBlur(float2 p, float r) {
    if (r < 0.6) return sceneAt(p);
    float3 acc = 0.0; float w = 0.0;
    [unroll] for (int i = 0; i < 12; i++) {
        float fi = (float)i;
        float a = fi * 2.39996323;
        float rr = r * sqrt((fi + 0.5) / 12.0);
        float k = 1.0 - 0.5 * fi / 12.0;
        acc += sceneAt(p + float2(cos(a), sin(a)) * rr) * k;
        w += k;
    }
    return acc / w;
}
float luma(float3 c) { return dot(c, float3(0.2126, 0.7152, 0.0722)); }
float sdRoundBox(float2 p, float2 b, float r) {
    float2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
float shape(float2 p) { return sdRoundBox(p - uCenter, uSize * 0.5, uSize.y * 0.5); }
float shapeDist(float2 p, out float2 n) {
    const float e = 0.5;
    float f = shape(p);
    float2 gr = float2(shape(p + float2(e, 0.0)) - shape(p - float2(e, 0.0)),
                       shape(p + float2(0.0, e)) - shape(p - float2(0.0, e))) / (2.0 * e);
    float gl = length(gr);
    n = gl > 1e-5 ? gr / gl : float2(0.0, -1.0);
    return f / max(gl, 0.25);
}
float2 shapeNormal(float2 p) { float2 n; shapeDist(p, n); return n; }

float4 ps_main(float4 pos : SV_Position) : SV_Target {
    float2 p = pos.xy;
    float m = saturate(uMat);
    // Шире — толще: размер^0.3 от паспортной капсулы 250 px.
    float thick = pow(max(uSize.x / 250.0, 1.0), 0.3);
    float bevel = 13.0 * thick;
    float amp = 41.0 * thick;

    float2 n;
    float dist = shapeDist(p, n);
    float cover = saturate(0.5 - dist);
    float sd = shape(p - float2(0.0, 8.0));
    float shadow = m * 0.035 * exp(-max(sd, 0.0) / 30.0) * smoothstep(-30.0, 0.0, sd);
    float4 under = float4(0.0, 0.0, 0.0, shadow * (1.0 - cover));
    if (cover <= 0.0) return under;

    float inside = max(-dist, 0.0);
    float t = saturate(1.0 - inside / bevel);
    float d = amp * m * uRefraction * (1.0 - sqrt(max(1.0 - t * t, 0.0)));
    float3 col = sceneBlur(p - n * d, 2.4 * m);
    col = col * lerp(1.0, 1.015, m) + 0.086 * m;

    // Блик: полоса 1 px цвета контента через vibrant-матрицу, два источника.
    float2 L = normalize(float2(0.7071, -0.7071));
    float rim = 1.0 - smoothstep(0.0, 1.0, inside);
    float w = pow(max(dot(n, L), 0.0), 3.0) + pow(max(-dot(n, L), 0.0), 3.0);
    float l = luma(col);
    float3 vib = saturate(1.45 * (l + 2.07 * (col - l)) + 0.05);
    col = lerp(col, vib, rim * (0.5 + 0.5 * w) * m);
    // Тёмная кромка iOS 27: на торцах толще и темнее.
    if (inside < 1.6) {
        float2 tg = float2(-n.y, n.x);
        float curv = length(shapeNormal(p + tg * 2.0) - shapeNormal(p - tg * 2.0)) / 4.0;
        float ends = saturate(curv * 28.0);
        float width = lerp(0.5, 1.0, ends);
        float mul = lerp(0.925, 0.83, ends);
        float band = 1.0 - smoothstep(width * 0.6, width + 0.4, inside);
        col *= lerp(1.0, mul, band * m);
    }

    float edge = 1.0 - smoothstep(1.0, 2.0, inside);
    float a;
    if (uMode < 0.5) {
        // Гибрид: шейдер держит кромку, где фон уже смещён больше пикселя, и
        // плавно уступает живой середине композитора.
        a = max(smoothstep(0.2, 0.55, t), edge);
    } else if (uMode < 1.5) {
        a = 1.0;
    } else {
        a = edge;
    }
    a *= cover;
    return float4(col * a, a) + under * (1.0 - a);
}
"""


def _compile(entry: str, target: str) -> tuple[int, int]:
    """D3DCompile → (указатель на байткод, размер), блоб держим живым."""
    compiler = ctypes.WinDLL("d3dcompiler_47")
    source = HLSL.encode("utf-8")
    blob, errors = c_void_p(), c_void_p()
    hr = compiler.D3DCompile(source, len(source), b"glass.hlsl", None, None, entry.encode(), target.encode(),
                             0, 0, byref(blob), byref(errors))
    if hr != 0:
        message = ""
        if errors.value:
            pointer = vcall(errors.value, 3, c_void_p, [])
            message = ctypes.string_at(pointer).decode("utf-8", "replace")
        raise OSError(f"шейдер {entry} не собрался: {message}")
    _KEEP.append(blob.value)
    return vcall(blob.value, 3, c_void_p, []), vcall(blob.value, 4, ctypes.c_size_t, [])


_KEEP: list = []
_vs_code, _vs_size = _compile("vs_main", "vs_5_0")
_ps_code, _ps_size = _compile("ps_main", "ps_5_0")
vertex_shader, pixel_shader = c_void_p(), c_void_p()
_check(vcall(device, 12, _HR, [_P, ctypes.c_size_t, _P, _PP], _vs_code, _vs_size, None, byref(vertex_shader)),
       "CreateVertexShader")
_check(vcall(device, 15, _HR, [_P, ctypes.c_size_t, _P, _PP], _ps_code, _ps_size, None, byref(pixel_shader)),
       "CreatePixelShader")

# ---------- композиция ----------

compositor = Compositor()
target = create_desktop_window_target(compositor, hwnd, is_topmost=False)
root = compositor.create_container_visual()
root.size = Vector2(WIN_W, WIN_H)
target.root = root

# Живая середина: фон под визуалом → размытие σ 2.4 → тон Apple. Матрица D2D —
# строки r, g, b, a и строка сдвига: out = in·1.015 + 0.086.
_gain, _lift = 1.015, 0.086
_matrix = [_gain, 0, 0, 0,
           0, _gain, 0, 0,
           0, 0, _gain, 0,
           0, 0, 0, 1,
           _lift, _lift, _lift, 0]
# «frost 2.4» лаборатории — радиус диска из 12 выборок с весами 1…0.54, а не σ:
# дисперсия такого ядра 0.223·r² на ось, то есть σ ≈ 0.47·r ≈ 1.13 px. Композитору
# нужна настоящая σ, иначе середина выходит вдвое мутнее кромки. Оптимизация
# QUALITY: BALANCED уменьшает картинку перед размытием.
_SIGMA = 0.472 * 2.4
_blur = comp_blur.GaussianBlurEffect(comp_blur.source_parameter("backdrop"), _SIGMA,
                                     props=[("f", _SIGMA), ("u", 2), ("u", 1)])
_tone = comp_blur.GaussianBlurEffect(None, name="Tone", clsid=CLSID_D2D1ColorMatrix,
                                     props=[("fa", _matrix), ("u", 1), ("b", True)], sources=[_blur.as_source],
                                     names={"ColorMatrix": 0, "AlphaMode": 1, "ClampOutput": 2})
_backdrop = compositor.create_backdrop_brush()
_interior_brush, _status, _keep_interior = comp_blur.effect_brush(compositor, _tone, {"backdrop": _backdrop})
print(f"[probe] фабрика эффекта середины: статус {_status}")

interior = compositor.create_sprite_visual()
interior.size = Vector2(PILL_W, PILL_H)
interior.offset = Vector3(MARGIN, MARGIN, 0)
_geometry = compositor.create_rounded_rectangle_geometry()
_geometry.size = Vector2(PILL_W, PILL_H)
_geometry.corner_radius = Vector2(PILL_H / 2, PILL_H / 2)
interior.clip = compositor.create_geometric_clip_with_geometry(_geometry)
comp_blur.set_sprite_brush(interior, _interior_brush)
root.children.insert_at_top(interior)

# Кромка: свопчейн шейдера поверх середины, во всё окно (тень тоже его).
_interop = qi(comp_blur.abi(compositor), IID_ICompositorInterop)
_surface = c_void_p()
_check(vcall(_interop, 4, _HR, [_P, _PP], swapchain, byref(_surface)), "CreateCompositionSurfaceForSwapChain")
_surface_brush = compositor.create_surface_brush()
_brush_iface = qi(comp_blur.abi(_surface_brush), IID_ICompositionSurfaceBrush)
_check(vcall(_brush_iface, 13, _HR, [_P], _surface.value), "put_Surface")
overlay = compositor.create_sprite_visual()
overlay.size = Vector2(WIN_W, WIN_H)
overlay.brush = _surface_brush
root.children.insert_at_top(overlay)

# ---------- захват и кадры ----------

MODES = ("гибрид", "весь захват", "без линзы")
state = {"mode": 0, "running": True}
_latest: dict = {"raw": None, "fresh": False}
_lock = threading.Lock()

if OFFLINE:
    # Контрастная подложка: на почти белом окне стекло с тоном Apple само белое,
    # и по снимку не понять, видна ли сквозь него сцена.
    from PySide6.QtGui import QColor, QFont, QPainter

    class _Stage(QWidget):
        def paintEvent(self, _event) -> None:
            painter = QPainter(self)
            colors = ("#1f6feb", "#f2cc60", "#2ea043", "#ffffff", "#d1242f", "#0d1117")
            band = self.height() / len(colors)
            for index, color in enumerate(colors):
                painter.fillRect(0, int(index * band), self.width(), int(band) + 1, QColor(color))
            painter.setFont(QFont("Segoe UI", 11))
            for row in range(0, self.height(), 18):
                painter.setPen(QColor("#000000") if (row // 18) % 2 else QColor("#ffffff"))
                painter.drawText(8, row + 14, "Съешь же ещё этих мягких французских булок, да выпей чаю " * 2)

    class _Stripes(QWidget):
        """Вертикальные полосы бегут вправо с постоянной скоростью: по их фазе
        внутри стекла и снаружи видно, на сколько кадров середина отстаёт."""

        SPEED = 480.0
        PERIOD = 64

        def __init__(self) -> None:
            super().__init__()
            self._start = time.perf_counter()
            self._timer = QTimer(self)
            self._timer.setInterval(4)
            self._timer.timeout.connect(self.update)
            self._timer.start()

        def paintEvent(self, _event) -> None:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor("#ffffff"))
            shift = (time.perf_counter() - self._start) * self.SPEED % self.PERIOD
            x = shift - self.PERIOD
            while x < self.width():
                painter.fillRect(int(round(x)), 0, self.PERIOD // 2, self.height(), QColor("#000000"))
                x += self.PERIOD

    _stage = _Stripes() if MEASURE else _Stage()
    _stage.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
    _stage.setGeometry(WIN_X, WIN_Y, WIN_W, WIN_H)
    _stage.show()
    _deadline = time.perf_counter() + 0.5
    while time.perf_counter() < _deadline:
        app.processEvents()
        time.sleep(0.01)
    # Фон для шейдера — один снимок до показа окна.
    _seed = _GdiGrabber()
    _latest["raw"] = _seed.grab(WIN_X, WIN_Y, WIN_W, WIN_H)
    _latest["fresh"] = True

user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE


def capture_loop() -> None:
    grabber = _GdiGrabber()
    try:
        while state["running"]:
            raw = grabber.grab(WIN_X, WIN_Y, WIN_W, WIN_H)
            if raw is not None:
                with _lock:
                    _latest["raw"] = raw
                    _latest["fresh"] = True
            else:
                time.sleep(0.004)
    finally:
        grabber.close()


def render_loop() -> None:
    params = Params()
    params.res[:] = (WIN_W, WIN_H)
    params.center[:] = (WIN_W / 2.0, WIN_H / 2.0)
    params.size[:] = (PILL_W, PILL_H)
    params.mat = 1.0
    viewport = D3D11_VIEWPORT(0, 0, WIN_W, WIN_H, 0, 1)
    rtvs = (c_void_p * 1)(rtv.value)
    srvs = (c_void_p * 1)(scene_srv.value)
    samplers = (c_void_p * 1)(sampler.value)
    buffers = (c_void_p * 1)(cbuffer.value)
    started = time.perf_counter()
    frames, window = 0, time.perf_counter()
    while state["running"]:
        with _lock:
            raw = _latest["raw"] if _latest["fresh"] else None
            _latest["fresh"] = False
        if raw is not None:
            vcall(context, 48, None, [_P, c_uint, _P, _P, c_uint, c_uint],
                  scene_tex, 0, None, raw.ctypes.data, WIN_W * 4, 0)
        params.mode = float(state["mode"])
        params.refraction = 0.0 if state["mode"] == 2 else 1.0
        params.time = time.perf_counter() - started
        vcall(context, 48, None, [_P, c_uint, _P, _P, c_uint, c_uint],
              cbuffer.value, 0, None, ctypes.addressof(params), 0, 0)

        vcall(context, 33, None, [c_uint, _P, _P], 1, rtvs, None)
        vcall(context, 44, None, [c_uint, _P], 1, byref(viewport))
        vcall(context, 24, None, [ctypes.c_int], 4)  # TRIANGLELIST
        vcall(context, 11, None, [_P, _P, c_uint], vertex_shader.value, None, 0)
        vcall(context, 9, None, [_P, _P, c_uint], pixel_shader.value, None, 0)
        vcall(context, 8, None, [c_uint, c_uint, _P], 0, 1, srvs)
        vcall(context, 10, None, [c_uint, c_uint, _P], 0, 1, samplers)
        vcall(context, 16, None, [c_uint, c_uint, _P], 0, 1, buffers)
        vcall(context, 13, None, [c_uint, c_uint], 3, 0)
        vcall(swapchain, 8, _HR, [c_uint, c_uint], 1, 0)

        frames += 1
        now = time.perf_counter()
        if now - window >= 5.0:
            print(f"[probe] {frames / (now - window):.0f} кадров/с, режим «{MODES[state['mode']]}»")
            frames, window = 0, now


if not OFFLINE:
    threading.Thread(target=capture_loop, name="capture", daemon=True).start()
threading.Thread(target=render_loop, name="render", daemon=True).start()


def _look() -> None:
    """Снимает плашку в каждом режиме, склеивает столбиком и выходит."""
    shots = []

    def shoot(index: int) -> None:
        if index > 0:
            shots.append(_seed.grab(WIN_X, WIN_Y, WIN_W, WIN_H))
        if index < len(MODES):
            state["mode"] = index
            QTimer.singleShot(700, lambda: shoot(index + 1))
            return
        from PySide6.QtGui import QImage

        sheet = np.ascontiguousarray(np.concatenate(shots, axis=0))
        sheet[..., 3] = 255
        QImage(sheet.data, sheet.shape[1], sheet.shape[0], sheet.shape[1] * 4,
               QImage.Format_RGB32).save(LOOK)
        print(f"[probe] снимок: {LOOK}")
        app.quit()

    QTimer.singleShot(900, lambda: shoot(0))


if LOOK is not None:
    _look()


def _profile(raw: np.ndarray, y: int, x0: int, x1: int) -> np.ndarray:
    row = raw[y, x0:x1, :3].astype(np.float32)
    lum = row @ np.array([0.0722, 0.7152, 0.2126], dtype=np.float32)  # BGR
    return (lum - lum.mean()) / max(float(lum.std()), 1e-3)


def _shift(inner: np.ndarray, outer: np.ndarray, reach: int = 30) -> int:
    """Сдвиг inner относительно outer по максимуму корреляции, px."""
    best, best_score = 0, -1e9
    for s in range(-reach, reach + 1):
        a = inner[reach + s: len(inner) - reach + s]
        b = outer[reach: len(outer) - reach]
        score = float((a * b).mean())
        if score > best_score:
            best, best_score = s, score
    return best


def _measure() -> None:
    """Сравнивает фазу полос внутри стекла (живая середина) и над плашкой."""
    state["mode"] = 2
    x0, x1 = MARGIN + 60, MARGIN + PILL_W - 60
    y_in, y_out, y_ctl = MARGIN + PILL_H // 2, MARGIN - 24, MARGIN - 40
    results: list[tuple[int, int]] = []
    phases: list[int] = []

    def sample(left: int) -> None:
        raw = _seed.grab(WIN_X, WIN_Y, WIN_W, WIN_H)
        if raw is not None:
            outer = _profile(raw, y_out, x0, x1)
            # Полосы бегут вправо: запоздавшая картинка сдвинута влево.
            results.append((-_shift(_profile(raw, y_in, x0, x1), outer),
                            -_shift(_profile(raw, y_ctl, x0, x1), outer)))
            # Фаза полос снаружи: если она не меняется, полосы стоят и ноль ничего не значит.
            edges = np.flatnonzero(np.diff((outer > 0).astype(np.int8)) > 0)
            phases.append(int(edges[0]) if len(edges) else -1)
        if left > 0:
            QTimer.singleShot(53, lambda: sample(left - 1))
            return
        lags = np.array([r[0] for r in results])
        control = np.array([r[1] for r in results])
        frame_px = _Stripes.SPEED / 60.0
        print(f"[measure] кадров: {len(results)}; полосы {_Stripes.SPEED:.0f} px/с = {frame_px:.1f} px за кадр 60 Гц")
        print(f"[measure] контроль (снаружи против снаружи): {sorted(set(control.tolist()))}")
        print(f"[measure] середина отстаёт, px: медиана {np.median(lags):.1f}, разброс {lags.min()}…{lags.max()}")
        print(f"[measure] это {np.median(lags) / _Stripes.SPEED * 1000:.1f} мс")
        print(f"[measure] фаза полос снаружи по кадрам: {phases[:16]}")
        app.quit()

    QTimer.singleShot(1200, lambda: sample(40))


if MEASURE:
    _measure()

# ---------- переключатель режимов ----------

panel = QWidget()
panel.setWindowTitle("Гибридное стекло")
panel.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
layout = QVBoxLayout(panel)
layout.addWidget(QLabel("Прокручивайте страницу под плашкой\nи сравнивайте режимы:"))
group = QButtonGroup(panel)
for index, title in enumerate(MODES):
    button = QRadioButton(title)
    button.setChecked(index == 0)
    group.addButton(button, index)
    layout.addWidget(button)
group.idClicked.connect(lambda index: state.update(mode=index))
panel.move(_area.left() + 24, _area.top() + 24)
panel.show()


def _quit() -> None:
    state["running"] = False


app.aboutToQuit.connect(_quit)
panel.destroyed.connect(app.quit)
panel.setAttribute(Qt.WA_DeleteOnClose, True)
QTimer.singleShot(0, lambda: print("[probe] плашка внизу экрана; закройте окно переключателя, чтобы выйти"))
sys.exit(app.exec())
