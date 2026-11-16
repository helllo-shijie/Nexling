# -*- mode: python ; coding: utf-8 -*-
# NexLing 目录式（onedir）打包：不释放临时解压目录，冷启动更快、体积可控。
# 产物：dist\NexLing\app\NexLingApp.exe（由 dist\NexLing\NexLing.exe 原生启动器拉起）
from PyInstaller.utils.hooks import collect_all

datas = [
    ('webui/dist', 'webui/dist'),
    ('laa_core/domain/skin/contrast_pairs.json', 'laa_core/domain/skin'),
]
binaries = []
hiddenimports = ['webview.platforms.edgechromium']
for pkg in ('webview', 'pythonnet', 'clr_loader'):
    tmp = collect_all(pkg)
    datas += tmp[0]
    binaries += tmp[1]
    hiddenimports += tmp[2]

a = Analysis(
    ['desktop.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'pytest', '_pytest', 'numpy', 'pandas', 'matplotlib', 'PIL',
        'IPython', 'sqlalchemy', 'websockets', 'setuptools', 'pkg_resources',
        'pip', 'wheel', 'lib2to3', 'pydoc', 'doctest',
        # 只有开发用 SSL 服务器需要，发布包不提供 HTTPS（cffi 是 pythonnet/clr_loader 的硬依赖，不能排除）
        'cryptography', 'OpenSSL',
        # pywebview 只用到 Windows 的 EdgeChromium 后端，其余 GUI 后端不打包
        'webview.platforms.gtk', 'webview.platforms.qt', 'webview.platforms.cef',
        'webview.platforms.mshtml',
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
    name='NexLingApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
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
    name='app',
)
