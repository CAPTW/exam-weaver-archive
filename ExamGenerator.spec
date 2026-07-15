# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# Package required SQL resources alongside the frozen Python modules.
# Runtime user data is copied to dist/ExamGenerator/data by build script.
datas = [
    ('src\\database\\schema.sql', 'src\\database'),
    ('src\\database\\seed.sql', 'src\\database'),
    ('src\\parser\\tessdata\\*.traineddata', 'src\\parser\\tessdata'),
    ('assets\\icons\\exam_generator_icon.ico', 'assets\\icons'),
    ('assets\\language_packs\\menu\\*.json', 'assets\\language_packs\\menu'),
    ('assets\\mathjax\\tex-mml-svg.js', 'assets\\mathjax'),
    ('assets\\mathjax\\LICENSE', 'assets\\mathjax'),
]
binaries = []
hiddenimports = []
tmp_ret = collect_all('qfluentwidgets')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('qframelesswindow')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
try:
    tmp_ret = collect_all('PyQt5.QtWebEngineWidgets')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass
tmp_ret = collect_all('openai_codex')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('codex_cli_bin')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['scripts\\run_gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ExamGenerator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets\\icons\\exam_generator_icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ExamGenerator',
)
