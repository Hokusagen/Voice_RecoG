"""Размытие живого фона силами системного композитора — без «Эффектов прозрачности».

HostBackdropBrush Windows 10 выдаёт только при включённой прозрачности, а
обычная BackdropBrush работает всегда, но отдаёт фон резким. Размыть её может
сам композитор через CompositionEffectBrush — нужен лишь объект-описание
эффекта (IGraphicsEffect + IGraphicsEffectD2D1Interop). pywinrt такие объекты
создавать не умеет, поэтому здесь он собран на ctypes по заголовкам Windows SDK
10.0.22621: порядок методов и IID взяты оттуда.
"""

from __future__ import annotations

import ctypes
import uuid
from ctypes import POINTER, WINFUNCTYPE, Structure, byref, c_float, c_long, c_uint32, c_ulong, c_void_p, sizeof
from ctypes import wintypes

# ---------- GUID и HSTRING ----------


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
IID_ICompositionEffectFactory = GUID.of("BE5624AF-BA7E-4510-9850-41C0B4FF74DF")
IID_ICompositionEffectBrush = GUID.of("BF7F795E-83CC-44BF-A447-3E3C071789EC")
IID_ICompositionBrush = GUID.of("AB0D7608-30C0-40E9-B568-B60A6BD1FB46")
IID_ISpriteVisual = GUID.of("08E05581-1AD1-4F97-9757-402D76E4233B")
IID_ICompositionEffectSourceParameterFactory = GUID.of("B3D9F276-ABA3-4724-ACF3-D0397464DB1C")
CLSID_D2D1GaussianBlur = GUID.of("1FEB6D69-2FE6-4AC9-8C58-1D7F93E7A6A5")

S_OK = 0
E_NOINTERFACE = ctypes.c_long(0x80004002).value
E_INVALIDARG = ctypes.c_long(0x80070057).value
E_BOUNDS = ctypes.c_long(0x8000000B).value

combase = ctypes.WinDLL("combase")
combase.WindowsCreateString.argtypes = [wintypes.LPCWSTR, c_uint32, POINTER(c_void_p)]
combase.WindowsCreateString.restype = ctypes.HRESULT
combase.WindowsDeleteString.argtypes = [c_void_p]
combase.WindowsGetStringRawBuffer.argtypes = [c_void_p, POINTER(c_uint32)]
combase.WindowsGetStringRawBuffer.restype = c_void_p
combase.RoGetActivationFactory.argtypes = [c_void_p, POINTER(GUID), POINTER(c_void_p)]
combase.RoGetActivationFactory.restype = ctypes.HRESULT


def hstring(text: str) -> c_void_p:
    handle = c_void_p()
    combase.WindowsCreateString(text, len(text), byref(handle))
    return handle


def hstring_text(handle: c_void_p | int | None) -> str:
    if not handle:
        return ""
    length = c_uint32()
    raw = combase.WindowsGetStringRawBuffer(handle, byref(length))
    return ctypes.wstring_at(raw, length.value) if raw else ""


# ---------- вызовы по таблице методов ----------


def vcall(ptr, index: int, restype, argtypes, *args):
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
    combase.WindowsDeleteString(handle)
    return text


# ---------- сырой указатель внутри объекта pywinrt ----------


class _MBI(Structure):
    _fields_ = [("BaseAddress", c_void_p), ("AllocationBase", c_void_p), ("AllocationProtect", wintypes.DWORD),
                ("PartitionId", wintypes.WORD), ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD)]


_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.VirtualQuery.argtypes = [c_void_p, POINTER(_MBI), ctypes.c_size_t]
_kernel32.VirtualQuery.restype = ctypes.c_size_t
_MEM_COMMIT, _MEM_IMAGE = 0x1000, 0x1000000


def _region(address: int) -> _MBI | None:
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
            if class_name(candidate) == type(obj).__name__ or class_name(candidate).endswith("." + type(obj).__name__):
                return candidate
        except OSError:
            continue
    raise RuntimeError(f"не нашёл указатель в {type(obj).__name__}")


# ---------- описание эффекта: гауссово размытие ----------

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


_LIVE: dict[int, "GaussianBlurEffect"] = {}
"""Живые описания по адресам их интерфейсов: колбэк получает только this."""

_property_statics: int | None = None


def _box_single(value: float) -> int:
    global _property_statics
    if _property_statics is None:
        factory = c_void_p()
        name = hstring("Windows.Foundation.PropertyValue")
        combase.RoGetActivationFactory(name, byref(IID_IPropertyValueStatics), byref(factory))
        combase.WindowsDeleteString(name)
        _property_statics = factory.value
    boxed = c_void_p()
    vcall(_property_statics, 14, ctypes.HRESULT, [c_float, POINTER(c_void_p)], c_float(value), byref(boxed))
    return boxed.value


def _box_uint32(value: int) -> int:
    _box_single(0.0) if _property_statics is None else None
    boxed = c_void_p()
    vcall(_property_statics, 11, ctypes.HRESULT, [c_uint32, POINTER(c_void_p)], c_uint32(value), byref(boxed))
    return boxed.value


def source_parameter(name: str) -> int:
    """CompositionEffectSourceParameter — именованный вход эффекта, как IGraphicsEffectSource."""
    factory = c_void_p()
    class_id = hstring("Windows.UI.Composition.CompositionEffectSourceParameter")
    combase.RoGetActivationFactory(class_id, byref(IID_ICompositionEffectSourceParameterFactory), byref(factory))
    combase.WindowsDeleteString(class_id)
    param = c_void_p()
    handle = hstring(name)
    vcall(factory.value, 6, ctypes.HRESULT, [c_void_p, POINTER(c_void_p)], handle, byref(param))
    combase.WindowsDeleteString(handle)
    release(factory.value)
    source = qi(param.value, IID_IGraphicsEffectSource)
    release(param.value)
    return source


def _box_bool(value: bool) -> int:
    _box_single(0.0) if _property_statics is None else None
    boxed = c_void_p()
    vcall(_property_statics, 17, ctypes.HRESULT, [ctypes.c_ubyte, POINTER(c_void_p)], ctypes.c_ubyte(bool(value)),
          byref(boxed))
    return boxed.value


def _box_floats(values) -> int:
    _box_single(0.0) if _property_statics is None else None
    array = (c_float * len(values))(*values)
    boxed = c_void_p()
    vcall(_property_statics, 33, ctypes.HRESULT, [c_uint32, POINTER(c_float), POINTER(c_void_p)],
          c_uint32(len(values)), array, byref(boxed))
    return boxed.value


class GaussianBlurEffect:
    """Описание эффекта Direct2D для композитора.

    По умолчанию — гауссово размытие (StandardDeviation, Optimization,
    BorderMode); clsid, props и sources дают любой другой эффект: props —
    список пар (вид, значение), вид 'f' | 'u' | 'b' | 'fa'; sources — указатели
    IGraphicsEffectSource (параметры-источники или вложенные описания).
    """

    def __init__(self, source: int, deviation: float = 0.0, name: str = "Blur",
                 clsid: GUID | None = None, props=None, sources=None) -> None:
        self.source = source
        self.deviation = deviation
        self.name = name
        self.clsid = clsid or CLSID_D2D1GaussianBlur
        self.props = props if props is not None else [("f", deviation), ("u", 1), ("u", 1)]
        self.sources = sources if sources is not None else [source]
        self._refs = 1

        inspectable = [_QI(self._qi), _REF(self._add_ref), _REF(self._release),
                       _GET_IIDS(self._get_iids), _GET_NAME(self._class_name), _TRUST(self._trust)]
        self._callbacks_effect = inspectable + [_GET_NAME(self._get_name), _PUT_NAME(self._put_name)]
        self._callbacks_source = list(inspectable)
        self._callbacks_interop = [_QI(self._qi), _REF(self._add_ref), _REF(self._release),
                                   _EFFECT_ID(self._effect_id), _MAPPING(self._mapping),
                                   _COUNT(self._property_count), _INDEXED(self._property),
                                   _INDEXED(self._get_source), _COUNT(self._source_count)]

        def table(callbacks):
            array = (c_void_p * len(callbacks))(*[ctypes.cast(cb, c_void_p) for cb in callbacks])
            return array

        self._tables = [table(self._callbacks_effect), table(self._callbacks_source),
                        table(self._callbacks_interop)]
        self._effect = _Iface(ctypes.addressof(self._tables[0]))
        self._source_iface = _Iface(ctypes.addressof(self._tables[1]))
        self._interop = _Iface(ctypes.addressof(self._tables[2]))
        for iface in (self._effect, self._source_iface, self._interop):
            _LIVE[ctypes.addressof(iface)] = self

    @property
    def pointer(self) -> int:
        """IGraphicsEffect* — то, что принимает CreateEffectFactory."""
        return ctypes.addressof(self._effect)

    # -- IUnknown / IInspectable --

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
        # Объект живёт, пока жив Python-владелец: счётчик только для порядка.
        self._refs -= 1
        return max(self._refs, 1)

    def _get_iids(self, _this, count, iids):
        count[0] = 0
        iids[0] = None
        return S_OK

    def _class_name(self, _this, out):
        out[0] = hstring("VoiceTyper.GaussianBlurEffect").value
        return S_OK

    def _trust(self, _this, level):
        level[0] = 0
        return S_OK

    # -- IGraphicsEffect --

    def _get_name(self, _this, out):
        out[0] = hstring(self.name).value
        return S_OK

    def _put_name(self, _this, handle):
        self.name = hstring_text(handle)
        return S_OK

    # -- IGraphicsEffectD2D1Interop --

    def _effect_id(self, _this, out):
        ctypes.memmove(out, byref(self.clsid), sizeof(GUID))
        return S_OK

    _NAMES = {"BlurAmount": 0, "Optimization": 1, "BorderMode": 2}

    def _mapping(self, _this, name, index, mapping):
        if name not in self._NAMES:
            return E_INVALIDARG
        index[0] = self._NAMES[name]
        mapping[0] = 1  # GRAPHICS_EFFECT_PROPERTY_MAPPING_DIRECT
        return S_OK

    def _property_count(self, _this, count):
        count[0] = len(self.props)
        return S_OK

    def _property(self, _this, index, out):
        # Для размытия: StandardDeviation, OPTIMIZATION_BALANCED и BORDER_MODE_HARD —
        # жёсткий край не даёт тёмного ореола по кромке.
        if index >= len(self.props):
            out[0] = None
            return E_BOUNDS
        kind, raw = self.props[index]
        boxed = {"f": _box_single, "u": _box_uint32, "b": _box_bool, "fa": _box_floats}[kind](raw)
        value = qi(boxed, IID_IPropertyValue)
        release(boxed)
        out[0] = value
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

    @property
    def as_source(self) -> int:
        """Это же описание как вход другого эффекта (IGraphicsEffectSource*)."""
        return ctypes.addressof(self._source_iface)


def blurred_backdrop_brush(compositor, backdrop_brush, deviation: float):
    """Кисть «живой фон под визуалом → гауссово размытие». Возвращает (кисть, что держать живым)."""
    effect = GaussianBlurEffect(source_parameter("backdrop"), deviation)
    comp = qi(abi(compositor), IID_ICompositor)
    factory = c_void_p()
    vcall(comp, 11, ctypes.HRESULT, [c_void_p, POINTER(c_void_p)], effect.pointer, byref(factory))
    brush = c_void_p()
    vcall(factory.value, 6, ctypes.HRESULT, [POINTER(c_void_p)], byref(brush))
    handle = hstring("backdrop")
    source = qi(abi(backdrop_brush), IID_ICompositionBrush)
    vcall(brush.value, 7, ctypes.HRESULT, [c_void_p, c_void_p], handle, source)
    combase.WindowsDeleteString(handle)
    return qi(brush.value, IID_ICompositionBrush), (effect, factory.value, brush.value, source, comp)


def effect_brush(compositor, effect: "GaussianBlurEffect", inputs: dict):
    """Кисть по произвольному описанию; inputs — {имя параметра: кисть pywinrt}.

    Возвращает (ICompositionBrush*, статус загрузки фабрики, что держать живым).
    """
    comp = qi(abi(compositor), IID_ICompositor)
    factory = c_void_p()
    vcall(comp, 11, ctypes.HRESULT, [c_void_p, POINTER(c_void_p)], effect.pointer, byref(factory))
    status = ctypes.c_int()
    vcall(factory.value, 8, ctypes.HRESULT, [POINTER(ctypes.c_int)], byref(status))
    brush = c_void_p()
    vcall(factory.value, 6, ctypes.HRESULT, [POINTER(c_void_p)], byref(brush))
    keep = [effect, factory.value, brush.value, comp]
    for name, value in inputs.items():
        handle = hstring(name)
        source = qi(abi(value), IID_ICompositionBrush)
        vcall(brush.value, 7, ctypes.HRESULT, [c_void_p, c_void_p], handle, source)
        combase.WindowsDeleteString(handle)
        keep.append(source)
    return qi(brush.value, IID_ICompositionBrush), status.value, keep


def set_sprite_brush(sprite, brush_ptr: int) -> None:
    """ISpriteVisual::put_Brush для кисти, которой нет обёртки pywinrt."""
    visual = qi(abi(sprite), IID_ISpriteVisual)
    vcall(visual, 7, ctypes.HRESULT, [c_void_p], brush_ptr)
    release(visual)
