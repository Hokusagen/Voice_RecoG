"""Direct3D 11 на ctypes: ровно столько, сколько нужно стеклу плашки.

Один полноэкранный треугольник и пиксельный шейдер, который рисует всю
плашку: преломление кромки, блик, тень, цвет итога, значок и подпись. Кадр
выводится в свопчейн для композиции — его показывает системный композитор
поверх живой середины (см. ui.lens_hud).

Номера методов в таблицах сверены с заголовками SDK 10.0.22621 (d3d11.h,
dxgi1_2.h). Устройство свободно-поточное: создаётся в интерфейсном потоке, а
контекст дальше трогает только поток кадров.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, Structure, byref, c_float, c_uint, c_void_p

from ui.comp import GUID, vcall

_HR = ctypes.HRESULT
_P = c_void_p
_PP = POINTER(c_void_p)

IID_IDXGIFactory2 = GUID.of("50c83a1c-e072-4c48-87b0-3630fa36a6d0")
IID_ID3D11Texture2D = GUID.of("6f15aaf2-d208-4e89-9ab4-489535d34f9c")

FORMAT_BGRA = 87  # DXGI_FORMAT_B8G8R8A8_UNORM


class _SwapChainDesc1(Structure):
    _fields_ = [("Width", c_uint), ("Height", c_uint), ("Format", ctypes.c_int), ("Stereo", ctypes.c_int),
                ("Count", c_uint), ("Quality", c_uint), ("BufferUsage", c_uint), ("BufferCount", c_uint),
                ("Scaling", ctypes.c_int), ("SwapEffect", ctypes.c_int), ("AlphaMode", ctypes.c_int),
                ("Flags", c_uint)]


class _Texture2DDesc(Structure):
    _fields_ = [("Width", c_uint), ("Height", c_uint), ("MipLevels", c_uint), ("ArraySize", c_uint),
                ("Format", ctypes.c_int), ("Count", c_uint), ("Quality", c_uint), ("Usage", ctypes.c_int),
                ("BindFlags", c_uint), ("CPUAccessFlags", c_uint), ("MiscFlags", c_uint)]


class _BufferDesc(Structure):
    _fields_ = [("ByteWidth", c_uint), ("Usage", ctypes.c_int), ("BindFlags", c_uint),
                ("CPUAccessFlags", c_uint), ("MiscFlags", c_uint), ("StructureByteStride", c_uint)]


class _SamplerDesc(Structure):
    _fields_ = [("Filter", ctypes.c_int), ("AddressU", ctypes.c_int), ("AddressV", ctypes.c_int),
                ("AddressW", ctypes.c_int), ("MipLODBias", c_float), ("MaxAnisotropy", c_uint),
                ("ComparisonFunc", ctypes.c_int), ("BorderColor", c_float * 4), ("MinLOD", c_float),
                ("MaxLOD", c_float)]


class _Viewport(Structure):
    _fields_ = [("TopLeftX", c_float), ("TopLeftY", c_float), ("Width", c_float), ("Height", c_float),
                ("MinDepth", c_float), ("MaxDepth", c_float)]


def _check(hr: int, what: str) -> None:
    if hr != 0:
        raise OSError(f"{what}: {hr & 0xFFFFFFFF:#010x}")


class Texture:
    """Текстура BGRA, которую шейдер читает, а процессор заливает целиком."""

    def __init__(self, device: int, width: int, height: int) -> None:
        self.width, self.height = width, height
        desc = _Texture2DDesc(width, height, 1, 1, FORMAT_BGRA, 1, 0, 0, 0x8, 0, 0)  # DEFAULT, SHADER_RESOURCE
        texture = c_void_p()
        _check(vcall(device, 5, _HR, [POINTER(_Texture2DDesc), _P, _PP], byref(desc), None, byref(texture)),
               "CreateTexture2D")
        self.texture = texture.value
        view = c_void_p()
        _check(vcall(device, 7, _HR, [_P, _P, _PP], self.texture, None, byref(view)), "CreateShaderResourceView")
        self.view = view.value


class Gpu:
    """Устройство, свопчейн во всё окно, шейдер и ресурсы одного кадра."""

    def __init__(self, width: int, height: int, hlsl: str, params_size: int) -> None:
        self.width, self.height = width, height
        d3d11 = ctypes.WinDLL("d3d11")
        device, context, level = c_void_p(), c_void_p(), c_uint()
        # BGRA_SUPPORT: без него свопчейн B8G8R8A8 для композиции не создаётся.
        _check(d3d11.D3D11CreateDevice(None, 1, None, 0x20, None, 0, 7, byref(device), byref(level),
                                       byref(context)), "D3D11CreateDevice")
        self.device, self.context = device.value, context.value

        factory = c_void_p()
        _check(ctypes.WinDLL("dxgi").CreateDXGIFactory2(0, byref(IID_IDXGIFactory2), byref(factory)),
               "CreateDXGIFactory2")
        # FLIP_SEQUENTIAL, два буфера, предумноженная альфа: снаружи пилюли окно прозрачно.
        desc = _SwapChainDesc1(width, height, FORMAT_BGRA, 0, 1, 0, 0x20, 2, 0, 3, 1, 0)
        swapchain = c_void_p()
        _check(vcall(factory.value, 24, _HR, [_P, POINTER(_SwapChainDesc1), _P, _PP],
                     self.device, byref(desc), None, byref(swapchain)), "CreateSwapChainForComposition")
        self.swapchain = swapchain.value

        backbuffer = c_void_p()
        _check(vcall(self.swapchain, 9, _HR, [c_uint, POINTER(GUID), _PP], 0, byref(IID_ID3D11Texture2D),
                     byref(backbuffer)), "GetBuffer")
        # В D3D11 с моделью flip нулевой буфер — всегда текущий задний: вид создаётся один раз.
        rtv = c_void_p()
        _check(vcall(self.device, 9, _HR, [_P, _P, _PP], backbuffer.value, None, byref(rtv)),
               "CreateRenderTargetView")
        self._rtvs = (c_void_p * 1)(rtv.value)

        sampler_desc = _SamplerDesc(0x15, 3, 3, 3, 0.0, 1, 8, (c_float * 4)(0, 0, 0, 0), 0.0, 3.4e38)
        sampler = c_void_p()
        _check(vcall(self.device, 23, _HR, [POINTER(_SamplerDesc), _PP], byref(sampler_desc), byref(sampler)),
               "CreateSamplerState")
        self._samplers = (c_void_p * 1)(sampler.value)

        buffer_desc = _BufferDesc((params_size + 15) // 16 * 16, 0, 0x4, 0, 0, 0)  # CONSTANT_BUFFER
        cbuffer = c_void_p()
        _check(vcall(self.device, 3, _HR, [POINTER(_BufferDesc), _P, _PP], byref(buffer_desc), None, byref(cbuffer)),
               "CreateBuffer")
        self.cbuffer = cbuffer.value
        self._buffers = (c_void_p * 1)(self.cbuffer)

        self._blobs: list[int] = []
        vs_code, vs_size = self._compile(hlsl, "vs_main", "vs_5_0")
        ps_code, ps_size = self._compile(hlsl, "ps_main", "ps_5_0")
        vs, ps = c_void_p(), c_void_p()
        _check(vcall(self.device, 12, _HR, [_P, ctypes.c_size_t, _P, _PP], vs_code, vs_size, None, byref(vs)),
               "CreateVertexShader")
        _check(vcall(self.device, 15, _HR, [_P, ctypes.c_size_t, _P, _PP], ps_code, ps_size, None, byref(ps)),
               "CreatePixelShader")
        self.vertex_shader, self.pixel_shader = vs.value, ps.value
        self._viewport = _Viewport(0, 0, width, height, 0, 1)

    def _compile(self, hlsl: str, entry: str, target: str) -> tuple[int, int]:
        compiler = ctypes.WinDLL("d3dcompiler_47")
        source = hlsl.encode("utf-8")
        blob, errors = c_void_p(), c_void_p()
        hr = compiler.D3DCompile(source, len(source), b"lens.hlsl", None, None, entry.encode(), target.encode(),
                                 0, 0, byref(blob), byref(errors))
        if hr != 0:
            message = ""
            if errors.value:
                message = ctypes.string_at(vcall(errors.value, 3, c_void_p, [])).decode("utf-8", "replace")
            raise OSError(f"шейдер {entry} не собрался: {message}")
        self._blobs.append(blob.value)
        return vcall(blob.value, 3, c_void_p, []), vcall(blob.value, 4, ctypes.c_size_t, [])

    def texture(self, width: int, height: int) -> Texture:
        return Texture(self.device, width, height)

    # -- дальше только поток кадров --

    def upload(self, texture: Texture, pixels: int, pitch: int) -> None:
        """Заливает текстуру целиком из памяти процессора (BGRA, pitch байт на строку)."""
        vcall(self.context, 48, None, [_P, c_uint, _P, _P, c_uint, c_uint], texture.texture, 0, None, pixels, pitch, 0)

    def draw(self, params, textures: list[Texture]) -> None:
        """Один кадр: константы, текстуры t0…tN, треугольник во весь экран и Present с vsync.

        Present(1) ждёт кадра композитора — поток кадров идёт в его темпе.
        """
        vcall(self.context, 48, None, [_P, c_uint, _P, _P, c_uint, c_uint],
              self.cbuffer, 0, None, ctypes.addressof(params), 0, 0)
        views = (c_void_p * len(textures))(*[t.view for t in textures])
        vcall(self.context, 33, None, [c_uint, _P, _P], 1, self._rtvs, None)
        vcall(self.context, 44, None, [c_uint, _P], 1, byref(self._viewport))
        vcall(self.context, 24, None, [ctypes.c_int], 4)  # TRIANGLELIST
        vcall(self.context, 11, None, [_P, _P, c_uint], self.vertex_shader, None, 0)
        vcall(self.context, 9, None, [_P, _P, c_uint], self.pixel_shader, None, 0)
        vcall(self.context, 8, None, [c_uint, c_uint, _P], 0, len(textures), views)
        vcall(self.context, 10, None, [c_uint, c_uint, _P], 0, 1, self._samplers)
        vcall(self.context, 16, None, [c_uint, c_uint, _P], 0, 1, self._buffers)
        vcall(self.context, 13, None, [c_uint, c_uint], 3, 0)
        vcall(self.swapchain, 8, _HR, [c_uint, c_uint], 1, 0)
