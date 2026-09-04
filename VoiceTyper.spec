# -*- mode: python ; coding: utf-8 -*-
"""Сборка VoiceTyper в автономный каталог.

Три вещи, без которых собранный .exe молча не работает или выглядит не так:

* faster_whisper тащит с собой onnx-модели детектора речи — без них падает
  vad_filter;
* ctranslate2 и onnxruntime кладут свои DLL рядом с пакетом, а не в системный
  путь, и собираются только через collect_all;
* шрифты из assets/fonts подключаются во время работы и в анализ импортов не
  попадают — их надо перечислить явно.

Приложение не консольное, поэтому при сбое смотреть
%APPDATA%/VoiceTyper/crash.log и voicetyper.log.
"""

import glob
import os
import sys

from PyInstaller.utils.hooks import collect_all

#: Лёгкая сборка: без faster-whisper и CUDA, распознаёт и правит только облако.
#: Включается переменной окружения VOICETYPER_LITE=1 (так делает build.py --lite).
LITE = os.environ.get("VOICETYPER_LITE", "").strip() not in ("", "0")
NAME = "VoiceTyper-lite" if LITE else "VoiceTyper"

datas = []
binaries = []
hiddenimports = []
if sys.platform == "win32":
    hiddenimports += ["win32clipboard", "win32con"]
else:
    hiddenimports += ["pynput.keyboard._darwin" if sys.platform == "darwin" else "pynput.keyboard._xorg"]

packages = ["sounddevice"]
if not LITE:
    packages += ["faster_whisper", "ctranslate2", "onnxruntime"]
for package in packages:
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# CUDA-библиотеки отдельно класть не нужно: collect_all("ctranslate2") уже
# положил их рядом с самим расширением, а Windows ищет зависимости в каталоге
# загружаемого модуля. Копия в nvidia/<пакет>/bin ради core.cuda_paths удваивала
# бы сборку — только cudnn весит около гигабайта.

# Шрифты подключаются во время работы, в анализ импортов не попадают.
# ui.theme ищет их относительно sys._MEIPASS, поэтому раскладка должна совпадать
# с той, что в исходниках.
for font in glob.glob(os.path.join("assets", "fonts", "*.ttf")):
    datas.append((font, os.path.join("assets", "fonts")))


a = Analysis(
    ["src/main.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Тянутся транзитивно, но приложению не нужны.
        "tkinter",
        "matplotlib",
        "PIL",
        "pystray",
        "plyer",
        "pyperclip",
    ] + (["faster_whisper", "ctranslate2", "onnxruntime", "torch"] if LITE else []),
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX ломает подписанные DLL Qt и CUDA — сжатие тут дороже, чем размер.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=NAME,
)

if sys.platform == "darwin":
    # Приложение живёт в строке меню: LSUIElement прячет его из Dock. Описания
    # разрешений обязательны, иначе macOS молча откажет в микрофоне и экране.
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        bundle_identifier="com.hokusagen.voicetyper",
        info_plist={
            "CFBundleDisplayName": "VoiceTyper",
            "CFBundleShortVersionString": os.environ.get("VOICETYPER_VERSION", "0.0.0"),
            "LSUIElement": True,
            "NSMicrophoneUsageDescription": "Микрофон нужен для диктовки.",
            "NSAppleEventsUsageDescription": "Вставка текста в активное окно.",
        },
    )
