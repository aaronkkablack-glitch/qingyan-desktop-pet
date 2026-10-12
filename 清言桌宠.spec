# -*- mode: python ; coding: utf-8 -*-
"""清言桌宠 onefile 打包配置：python -m PyInstaller 清言桌宠.spec

只带运行必需素材（帧序列/立绘/图标 ≈26MB）；HD文件(源视频75M)、_pre_fix/_original
备份、HD底图、废弃的 sheet/static-base 是生成管线产物，不进 exe。
config.json / data/ 不打包（用户数据在 exe 旁生成）。
"""

datas = [
    ("rules_bridge/judge.exe", "rules_bridge"),
    ("assets", "assets"),
    ("GLM形象参考图/成女头像.png", "assets"),
    ("静态图/帧序列", "静态图/帧序列"),
    ("静态图/少女.png", "静态图"),
    ("静态图/成女.png", "静态图"),
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="清言V1.0",
    icon="assets/app.ico",
    console=False,
    uac_admin=False,
)
