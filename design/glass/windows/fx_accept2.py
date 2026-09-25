"""Приём эффектов фабрикой композитора, с именами свойств как у Win2D (GetNamedPropertyMapping)."""
import ctypes, sys
from ctypes import wintypes
sys.path.insert(0, ".")
import comp_blur as cb

class DQO(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("threadType", ctypes.c_int), ("apartmentType", ctypes.c_int)]
ctypes.windll.ole32.CoInitializeEx(None, 2)
_dq = ctypes.c_void_p()
ctypes.WinDLL("CoreMessaging").CreateDispatcherQueueController(DQO(ctypes.sizeof(DQO), 2, 0), ctypes.byref(_dq))
from winrt.windows.ui.composition import Compositor
compositor = Compositor()

class Fx(cb.GaussianBlurEffect):
    def __init__(self, clsid, props, n_src, names, name):
        super().__init__(0, clsid=cb.GUID.of(clsid), props=props,
                         sources=[cb.source_parameter(f"s{i}") for i in range(n_src)], name=name)
        self._names = names
    def _mapping(self, _this, name, index, mapping):
        if name not in self._names:
            return cb.E_INVALIDARG
        index[0], mapping[0] = self._names[name]
        return cb.S_OK

def accept(label, fx):
    try:
        comp = cb.qi(cb.abi(compositor), cb.IID_ICompositor)
        factory = ctypes.c_void_p()
        cb.vcall(comp, 11, ctypes.HRESULT, [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)], fx.pointer, ctypes.byref(factory))
        st = ctypes.c_int(); cb.vcall(factory.value, 8, ctypes.HRESULT, [ctypes.POINTER(ctypes.c_int)], ctypes.byref(st))
        print(f"  {label:44s} ПРИНЯТ (LoadStatus={st.value})")
    except OSError as e:
        print(f"  {label:44s} отказ {e.winerror & 0xFFFFFFFF:#x}")

D = 1  # GRAPHICS_EFFECT_PROPERTY_MAPPING_DIRECT
ident = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1, 0,0,0,0]
goo = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,18, 0,0,0,-7]
tests = [] if __name__ != '__main__' else [
  ("ColorMatrix alpha=0 (как Win2D) без имён", Fx("921F03D6-641C-47DF-852D-B4BB6153AE11", [("fa", goo), ("u", 0), ("b", False)], 1, {}, "CM")),
  ("ColorMatrix alpha=1 без имён", Fx("921F03D6-641C-47DF-852D-B4BB6153AE11", [("fa", goo), ("u", 1), ("b", False)], 1, {}, "CM")),
  ("ColorMatrix alpha=1 с именами", Fx("921F03D6-641C-47DF-852D-B4BB6153AE11", [("fa", goo), ("u", 1), ("b", False)], 1,
        {"ColorMatrix": (0, D), "AlphaMode": (1, 6), "ClampOutput": (2, D)}, "CM")),
  ("ColorMatrix alpha=0 с именами", Fx("921F03D6-641C-47DF-852D-B4BB6153AE11", [("fa", goo), ("u", 0), ("b", False)], 1,
        {"ColorMatrix": (0, D), "AlphaMode": (1, 6), "ClampOutput": (2, D)}, "CM")),
  ("GammaTransfer (порог по альфе 18a-7)", Fx("409444C4-C419-41A0-B0C1-8CD0C0A18E42",
        [("f",1),("f",1),("f",0),("b",True), ("f",1),("f",1),("f",0),("b",True), ("f",1),("f",1),("f",0),("b",True),
         ("f",18),("f",1),("f",-7),("b",False), ("b",True)], 1, {}, "Gamma")),
  ("Transform2D без имён", Fx("6AA97485-6354-4CFC-908C-E4A74F62C96C", [("u",1),("u",0),("fa",[1.1,0,0,1.1,-20,-4]),("f",0.0)], 1, {}, "T2D")),
  ("Transform2D с именами", Fx("6AA97485-6354-4CFC-908C-E4A74F62C96C", [("u",1),("u",0),("fa",[1.1,0,0,1.1,-20,-4]),("f",0.0)], 1,
        {"InterpolationMode": (0, D), "BorderMode": (1, D), "TransformMatrix": (2, D), "Sharpness": (3, D)}, "T2D")),
  ("AlphaMask (2 входа)", Fx("C80ECFF0-3FD5-4F05-8328-C5D1724B4F0A", [], 2, {}, "AM")),
  ("Composite DestinationIn (2 входа)", Fx("48FC9F51-F6AC-48F1-8B58-3B28AC46F76D", [("u", 3)], 2, {}, "Comp")),
  ("LuminanceToAlpha", Fx("41251AB7-0BEB-46F8-9DA7-59E93FCCE5DE", [], 1, {}, "L2A")),
  ("ArithmeticComposite", Fx("FC151437-049A-4784-A24A-F1C4DAF20987", [("fa",[0,1,1,0]),("b",True)], 2, {}, "Arith")),
  ("PointSpecular (альфа как высота)", Fx("09C3CA26-3AE2-4F09-9EBC-ED3865D53F22",
        [("fa",[100,0,60]),("f",20),("f",1),("f",4),("fa",[1,1,1]),("fa",[1,1]),("u",1)], 1, {}, "Spec")),
  ("DistantSpecular", Fx("428C1EE5-77B8-4450-8AB5-72219C21ABDA",
        [("f",45),("f",45),("f",20),("f",1),("f",1),("fa",[1,1,1]),("fa",[1,1]),("u",1)], 1, {}, "DSpec")),
  ("Exposure", Fx("B56C8CFA-F634-41EE-BEE0-FFA617106004", [("f", 1.0)], 1, {}, "Exp")),
  ("DisplacementMap (контроль, ждём отказ)", Fx("EDC48364-0417-4111-9450-43845FA9F890", [("f",40.0),("u",0),("u",1)], 2, {}, "Disp")),
]
if __name__ == '__main__':
    for label, fx in tests:
        accept(label, fx)
