# -*- mode: python ; coding: utf-8 -*-
"""清言桌宠 onefile 打包配置：python -m PyInstaller 清言桌宠.spec

只带运行必需素材（帧序列/sheet/底图/立绘 ≈30MB）；HD文件(源视频75M)、_pre_fix/_original
备份、HD底图是生成管线用的，不进 exe。config.json / data/ 不打包（用户数据在 exe 旁生成）。
"""
import glob

datas = [
    ("rules_bridge/judge.exe", "rules_bridge"),
    ("assets", "assets"),
    ("GLM形象参考图/成女头像.png", "assets"),
    ("静态图/帧序列", "静态图/帧序列"),
    ("静态图/少女.png", "静态图"),
    ("静态图/成女.png", "静态图"),
]
datas += [(p, "静态图") for p in glob.glob("静态图/*-sheet.png")]
datas += [(p, "静态图") for p in glob.glob("静态图/*-static-base.png")]

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
