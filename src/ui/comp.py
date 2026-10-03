"""Мост к системному композитору Windows (Windows.UI.Composition).

Композитор собирает кадр вместе со всем экраном, поэтому живой фон под
плашкой (BackdropBrush) у него не отстаёт ни на кадр — в отличие от любого
захвата экрана. pywinrt даёт сам композитор и визуалы, но не умеет двух
вещей, без которых стекла нет:

- описать эффект Direct2D (размытие, цветовая матрица) — объект с
  интерфейсами IGraphicsEffect и IGraphicsEffectD2D1Interop собран здесь на
  ctypes по заголовкам Windows SDK 10.0.22621;
- встроить в композицию свопчейн D3D11 — через ICompositorInterop, до
  которого pywinrt не пускает: сырой указатель достаётся из его объекта.

Только Windows 10 1809+. Импорт модуля на других системах не падает, падает
первое обращение к WinRT.
"""

from __future__ import annotations

import ctypes
import uuid
from ctypes import POINTER, WINFUNCTYPE, Structure, byref, c_float, c_long, c_uint32, c_ulong, c_void_p, sizeof
from ctypes import wintypes


class GUID(Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text: str) -> "GUID":
        value = uuid.UUID(text)
        guid = cls(value.fields[0], value.fields[1], value.fields[2])
        guid.Data4[:] = list(value.bytes[8:])
        return guid

    def key(self) -> bytes:
        return bytes(memoryview(self))


IID_IUnknown = GUID.of("00000000-0000-0000-C000-000000000046")
IID_IInspectable = GUID.of("AF86E2E0-B12D-4C6A-9C5A-D7AA65101E90")
IID_IAgileObject = GUID.of("94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90")
IID_IGraphicsEffect = GUID.of("CB51C0CE-8FE6-4636-B202-861FAA07D8F3")
IID_IGraphicsEffectSource = GUID.of("2D8F9DDC-4339-4EB9-9216-F9DEB75658A2")
IID_IGraphicsEffectD2D1Interop = GUID.of("2FC57384-A068-44D7-A331-30982FCF7177")
IID_IPropertyValue = GUID.of("4BD682DD-7554-40E9-9A9B-82654EDE7E62")
IID_IPropertyValueStatics = GUID.of("629BDBC8-D932-4FF4-96B9-8D96C5C1E858")
IID_ICompositor = GUID.of("B403CA50-7F8C-4E83-985F-CC45060036D8")
IID_ICompositionBrush = GUID.of("AB0D7608-30C0-40E9-B568-B60A6BD1FB46")
IID_ISpriteVisual = GUID.of("08E05581-1AD1-4F97-9757-402D76E4233B")
IID_ICompositionEffectSourceParameterFactory = GUID.of("B3D9F276-ABA3-4724-ACF3-D0397464DB1C")
IID_ICompositorInterop = GUID.of("25297D5C-3AD4-4C9C-B5CF-E36A38512330")
IID_ICompositionSurfaceBrush = GUID.of("AD016D79-1E4C-4C0D-9C29-83338C87C162")

CLSID_GaussianBlur = GUID.of("1FEB6D69-2FE6-4AC9-8C58-1D7F93E7A6A5")
CLSID_ColorMatrix = GUID.of("921F03D6-641C-47DF-852D-B4BB6153AE11")

S_OK = 0
E_NOINTERFACE = ctypes.c_long(0x80004002).value
E_INVALIDARG = ctypes.c_long(0x80070057).value
E_BOUNDS = ctypes.c_long(0x8000000B).value

_combase = None


def _base():
    global _combase
    if _combase is None:
        lib = ctypes.WinDLL("combase")
        lib.WindowsCreateString.argtypes = [wintypes.LPCWSTR, c_uint32, POINTER(c_void_p)]
        lib.WindowsCreateString.restype = ctypes.HRESULT
        lib.WindowsDeleteString.argtypes = [c_void_p]
        lib.WindowsGetStringRawBuffer.argtypes = [c_void_p, POINTER(c_uint32)]
        lib.WindowsGetStringRawBuffer.restype = c_void_p
        lib.RoGetActivationFactory.argtypes = [c_void_p, POINTER(GUID), POINTER(c_void_p)]
        lib.RoGetActivationFactory.restype = ctypes.HRESULT
        _combase = lib
    return _combase


def hstring(text: str) -> c_void_p:
    handle = c_void_p()
    _base().WindowsCreateString(text, len(text), byref(handle))
    return handle


def hstring_text(handle) -> str:
    if not handle:
        return ""
    length = c_uint32()
    raw = _base().WindowsGetStringRawBuffer(handle, byref(length))
    return ctypes.wstring_at(raw, length.value) if raw else ""


def delete_hstring(handle) -> None:
    _base().WindowsDeleteString(handle)


def activation_factory(class_name: str, iid: GUID) -> int:
    factory = c_void_p()
    name = hstring(class_name)
    try:
        _base().RoGetActivationFactory(name, byref(iid), byref(factory))
    finally:
        delete_hstring(name)
    return factory.value


# ---------- вызовы по таблице методов ----------


def vcall(ptr, index: int, restype, argtypes, *args):
    """Метод COM по номеру в таблице: порядок сверен с заголовками SDK."""
    table = ctypes.cast(c_void_p(ptr), POINTER(POINTER(c_void_p)))[0]
    return WINFUNCTYPE(restype, c_void_p, *argtypes)(table[index])(ptr, *args)


def qi(ptr, iid: GUID) -> int:
    out = c_void_p()
    vcall(ptr, 0, ctypes.HRESULT, [POINTER(GUID), POINTER(c_void_p)], byref(iid), byref(out))
    return out.value


def add_ref(ptr) -> None:
    vcall(ptr, 1, c_ulong, [])


def release(ptr) -> None:
    vcall(ptr, 2, c_ulong, [])


def class_name(ptr) -> str:
    handle = c_void_p()
    vcall(ptr, 4, ctypes.HRESULT, [POINTER(c_void_p)], byref(handle))
    text = hstring_text(handle)
    delete_hstring(handle)
    return text


# ---------- сырой указатель внутри объекта pywinrt ----------


class _MBI(Structure):
    _fields_ = [("BaseAddress", c_void_p), ("AllocationBase", c_void_p), ("AllocationProtect", wintypes.DWORD),
                ("PartitionId", wintypes.WORD), ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]


_MEM_COMMIT, _MEM_IMAGE = 0x1000, 0x1000000
_kernel32 = None


def _region(address: int) -> _MBI | None:
    global _kernel32
    if _kernel32 is None:
        _kernel32 = ctypes.WinDLL("kernel32")
        _kernel32.VirtualQuery.argtypes = [c_void_p, POINTER(_MBI), ctypes.c_size_t]
        _kernel32.VirtualQuery.restype = ctypes.c_size_t
    info = _MBI()
    if not address or not _kernel32.VirtualQuery(c_void_p(address), byref(info), sizeof(info)):
        return None
    if info.State != _MEM_COMMIT or info.Protect & 0x101:  # NOACCESS, GUARD
        return None
    return info


def abi(obj) -> int:
    """Указатель на интерфейс по умолчанию, который держит объект pywinrt.

    Публично pywinrt его не отдаёт. Объект на C++ — заголовок PyObject и сразу
    умный указатель; кандидата проверяем, не разыменовывая вслепую: таблица
    методов обязана лежать в образе DLL, а имя класса — совпасть.
    """
    base = id(obj)
    for offset in (16, 24, 32, 40, 48):
        candidate = c_void_p.from_address(base + offset).value
        if not _region(candidate or 0):
            continue
        table = c_void_p.from_address(candidate).value
        table_region = _region(table or 0)
        if not table_region or table_region.Type != _MEM_IMAGE:
            continue
        first = c_void_p.from_address(table).value
        first_region = _region(first or 0)
        if not first_region or first_region.Type != _MEM_IMAGE:
            continue
        try:
            name = class_name(candidate)
        except OSError:
            continue
        if name == type(obj).__name__ or name.endswith("." + type(obj).__name__):
            return candidate
    raise RuntimeError(f"не нашёл указатель в {type(obj).__name__}")


# ---------- значения свойств эффекта ----------

_property_statics: int | None = None


def _statics() -> int:
    global _property_statics
    if _property_statics is None:
        _property_statics = activation_factory("Windows.Foundation.PropertyValue", IID_IPropertyValueStatics)
    return _property_statics


def _box(kind: str, value) -> int:
    """PropertyValue нужного типа; номера методов — IPropertyValueStatics."""
    boxed = c_void_p()
    if kind == "f":
        vcall(_statics(), 14, ctypes.HRESULT, [c_float, POINTER(c_void_p)], c_float(value), byref(boxed))
    elif kind == "u":
        vcall(_statics(), 11, ctypes.HRESULT, [c_uint32, POINTER(c_void_p)], c_uint32(value), byref(boxed))
    elif kind == "b":
        vcall(_statics(), 17, ctypes.HRESULT, [ctypes.c_ubyte, POINTER(c_void_p)], ctypes.c_ubyte(bool(value)),
              byref(boxed))
    else:  # "fa": массив float
        array = (c_float * len(value))(*value)
        vcall(_statics(), 33, ctypes.HRESULT, [c_uint32, POINTER(c_float), POINTER(c_void_p)],
              c_uint32(len(value)), array, byref(boxed))
    return boxed.value


def source_parameter(name: str) -> int:
    """CompositionEffectSourceParameter — именованный вход эффекта (IGraphicsEffectSource*)."""
    factory = activation_factory("Windows.UI.Composition.CompositionEffectSourceParameter",
                                 IID_ICompositionEffectSourceParameterFactory)
    param = c_void_p()
    handle = hstring(name)
    vcall(factory, 6, ctypes.HRESULT, [c_void_p, POINTER(c_void_p)], handle, byref(param))
    delete_hstring(handle)
    release(factory)
    source = qi(param.value, IID_IGraphicsEffectSource)
    release(param.value)
    return source


# ---------- описание эффекта ----------

_HR = c_long
_QI = WINFUNCTYPE(_HR, c_void_p, POINTER(GUID), POINTER(c_void_p))
_REF = WINFUNCTYPE(c_ulong, c_void_p)
_GET_IIDS = WINFUNCTYPE(_HR, c_void_p, POINTER(c_uint32), POINTER(c_void_p))
_GET_NAME = WINFUNCTYPE(_HR, c_void_p, POINTER(c_void_p))
_TRUST = WINFUNCTYPE(_HR, c_void_p, POINTER(ctypes.c_int))
_PUT_NAME = WINFUNCTYPE(_HR, c_void_p, c_void_p)
_EFFECT_ID = WINFUNCTYPE(_HR, c_void_p, POINTER(GUID))
_MAPPING = WINFUNCTYPE(_HR, c_void_p, wintypes.LPCWSTR, POINTER(c_uint32), POINTER(ctypes.c_int))
_COUNT = WINFUNCTYPE(_HR, c_void_p, POINTER(c_uint32))
_INDEXED = WINFUNCTYPE(_HR, c_void_p, c_uint32, POINTER(c_void_p))


class _Iface(Structure):
    _fields_ = [("vtbl", c_void_p)]


class Effect:
    """Описание эффекта Direct2D для фабрики композитора.

    props — список пар (вид, значение) по номерам свойств D2D, вид 'f' | 'u' |
    'b' | 'fa'; sources — входы (IGraphicsEffectSource*: параметры или вложенные
    описания); names — имена свойств как у Win2D, нужны только для анимации.
    Объект живёт, пока жив Python-владелец: счётчик ссылок только для порядка.
    """

    def __init__(self, clsid: GUID, props, sources, name: str = "Effect", names=None) -> None:
        self.clsid = clsid
        self.props = list(props)
        self.sources = list(sources)
        self.name = name
        self.names = dict(names or {})
        self._refs = 1

        inspectable = [_QI(self._qi), _REF(self._add_ref), _REF(self._release),
                       _GET_IIDS(self._get_iids), _GET_NAME(self._class_name), _TRUST(self._trust)]
        self._callbacks = [
            inspectable + [_GET_NAME(self._get_name), _PUT_NAME(self._put_name)],
            list(inspectable),
            [_QI(self._qi), _REF(self._add_ref), _REF(self._release), _EFFECT_ID(self._effect_id),
             _MAPPING(self._mapping), _COUNT(self._property_count), _INDEXED(self._property),
             _INDEXED(self._get_source), _COUNT(self._source_count)],
        ]
        self._tables = [(c_void_p * len(cbs))(*[ctypes.cast(cb, c_void_p) for cb in cbs]) for cbs in self._callbacks]
        self._effect, self._source_iface, self._interop = (_Iface(ctypes.addressof(t)) for t in self._tables)

    @property
    def pointer(self) -> int:
        """IGraphicsEffect* — то, что принимает CreateEffectFactory."""
        return ctypes.addressof(self._effect)

    @property
    def as_source(self) -> int:
        """Это же описание как вход другого эффекта."""
        return ctypes.addressof(self._source_iface)

    def _qi(self, _this, riid, out):
        key = riid.contents.key()
        if key in (IID_IUnknown.key(), IID_IInspectable.key(), IID_IGraphicsEffect.key(), IID_IAgileObject.key()):
            target = self._effect
        elif key == IID_IGraphicsEffectSource.key():
            target = self._source_iface
        elif key == IID_IGraphicsEffectD2D1Interop.key():
            target = self._interop
        else:
            out[0] = None
            return E_NOINTERFACE
        out[0] = ctypes.addressof(target)
        self._refs += 1
        return S_OK

    def _add_ref(self, _this):
        self._refs += 1
        return self._refs

    def _release(self, _this):
        self._refs -= 1
        return max(self._refs, 1)

    def _get_iids(self, _this, count, iids):
        count[0] = 0
        iids[0] = None
        return S_OK

    def _class_name(self, _this, out):
        out[0] = hstring("VoiceTyper.Effect").value
        return S_OK

    def _trust(self, _this, level):
        level[0] = 0
        return S_OK

    def _get_name(self, _this, out):
        out[0] = hstring(self.name).value
        return S_OK

    def _put_name(self, _this, handle):
        self.name = hstring_text(handle)
        return S_OK

    def _effect_id(self, _this, out):
        ctypes.memmove(out, byref(self.clsid), sizeof(GUID))
        return S_OK

    def _mapping(self, _this, name, index, mapping):
        if name not in self.names:
            return E_INVALIDARG
        index[0] = self.names[name]
        mapping[0] = 1  # GRAPHICS_EFFECT_PROPERTY_MAPPING_DIRECT
        return S_OK

    def _property_count(self, _this, count):
        count[0] = len(self.props)
        return S_OK

    def _property(self, _this, index, out):
        if index >= len(self.props):
            out[0] = None
            return E_BOUNDS
        boxed = _box(*self.props[index])
        out[0] = qi(boxed, IID_IPropertyValue)
        release(boxed)
        return S_OK

    def _get_source(self, _this, index, out):
        if index >= len(self.sources):
            out[0] = None
            return E_BOUNDS
        add_ref(self.sources[index])
        out[0] = self.sources[index]
        return S_OK

    def _source_count(self, _this, count):
        count[0] = len(self.sources)
        return S_OK


def gaussian_blur(source: int, sigma: float) -> Effect:
    # OPTIMIZATION_QUALITY: BALANCED уменьшает картинку перед размытием, и при
    # малой σ середина выходила заметно мутнее заданной. BORDER_MODE_HARD.
    return Effect(CLSID_GaussianBlur, [("f", sigma), ("u", 2), ("u", 1)], [source], "Frost",
                  {"BlurAmount": 0, "Optimization": 1, "BorderMode": 2})


def color_matrix(source: int, matrix: list[float]) -> Effect:
    """Матрица 5×4 D2D: строки r, g, b, a и строка сдвига; out_j = Σ in_i·M[i][j] + M[4][j]."""
    return Effect(CLSID_ColorMatrix, [("fa", matrix), ("u", 1), ("b", True)], [source], "Tone",
                  {"ColorMatrix": 0, "AlphaMode": 1, "ClampOutput": 2})


def effect_brush(compositor, effect: Effect, inputs: dict) -> tuple[int, list]:
    """Кисть по описанию; inputs — {имя параметра: кисть pywinrt}.

    Возвращает (ICompositionBrush*, что держать живым, пока кисть в деле).
    """
    comp = qi(abi(compositor), IID_ICompositor)
    factory = c_void_p()
    vcall(comp, 11, ctypes.HRESULT, [c_void_p, POINTER(c_void_p)], effect.pointer, byref(factory))
    brush = c_void_p()
    vcall(factory.value, 6, ctypes.HRESULT, [POINTER(c_void_p)], byref(brush))
    keep = [effect, factory.value, brush.value, comp]
    for name, value in inputs.items():
        handle = hstring(name)
        source = qi(abi(value), IID_ICompositionBrush)
        vcall(brush.value, 7, ctypes.HRESULT, [c_void_p, c_void_p], handle, source)
        delete_hstring(handle)
        keep.append(source)
    return qi(brush.value, IID_ICompositionBrush), keep


def set_sprite_brush(sprite, brush_ptr: int) -> None:
    """ISpriteVisual::put_Brush для кисти, которой нет обёртки pywinrt."""
    visual = qi(abi(sprite), IID_ISpriteVisual)
    vcall(visual, 7, ctypes.HRESULT, [c_void_p], brush_ptr)
    release(visual)


def swapchain_surface(compositor, swapchain: int) -> int:
    """ICompositorInterop::CreateCompositionSurfaceForSwapChain → ICompositionSurface*."""
    interop = qi(abi(compositor), IID_ICompositorInterop)
    surface = c_void_p()
    hr = vcall(interop, 4, ctypes.HRESULT, [c_void_p, POINTER(c_void_p)], swapchain, byref(surface))
    release(interop)
    if hr != 0:
        raise OSError(f"CreateCompositionSurfaceForSwapChain: {hr & 0xFFFFFFFF:#010x}")
    return surface.value


def set_brush_surface(surface_brush, surface: int) -> None:
    """ICompositionSurfaceBrush::put_Surface для сырого ICompositionSurface*."""
    brush = qi(abi(surface_brush), IID_ICompositionSurfaceBrush)
    vcall(brush, 13, ctypes.HRESULT, [c_void_p], surface)
    release(brush)


class _DispatcherOptions(Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("threadType", ctypes.c_int), ("apartmentType", ctypes.c_int)]


_dispatcher = None


def ensure_dispatcher_queue() -> None:
    """Очередь диспетчера в текущем (интерфейсном) потоке: без неё композитор не создаётся.

    COM к этому моменту уже поднял Qt, поэтому apartmentType = DQTAT_COM_NONE.
    """
    global _dispatcher
    if _dispatcher is not None:
        return
    controller = c_void_p()
    hr = ctypes.WinDLL("CoreMessaging").CreateDispatcherQueueController(
        _DispatcherOptions(sizeof(_DispatcherOptions), 2, 0), byref(controller))
    if hr != 0:
        raise OSError(f"CreateDispatcherQueueController: {hr & 0xFFFFFFFF:#010x}")
    _dispatcher = controller
