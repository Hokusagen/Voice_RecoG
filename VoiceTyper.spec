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

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ["win32clipboard", "win32con"]

for package in ("faster_whisper", "ctranslate2", "onnxruntime", "sounddevice"):
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
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoiceTyper",
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
    name="VoiceTyper",
)
