# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path.cwd()

datas = [
    (str(project_root / "config"), "config"),
    (str(project_root / "presets"), "presets"),
    (str(project_root / "README.md"), "."),
    (str(project_root / "LICENSE"), "."),
]

hiddenimports = [
    "cv2",
    "scenedetect",
    "src",
    "src.gameplay_pipeline",
]

a = Analysis(
    [str(project_root / "gameplay_pipeline_v1.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GameplayHighlightPipeline",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="GameplayHighlightPipeline",
)
