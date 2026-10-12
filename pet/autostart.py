# -*- coding: utf-8 -*-
"""开机自启（Windows HKCU Run 键，无需管理员权限）。

源码模式注册 pythonw main.py；打包 exe 注册自身路径。注册表是唯一事实源
（设置页打开时读它，不存 config——避免两处状态漂移）。
"""
import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "清言V1.0"


def _command() -> str:
    """自启命令行：frozen=exe 自身；源码=pythonw main.py（引号包路径防空格）。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pythonw):
        exe = pythonw
    main = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    return f'"{exe}" "{main}"'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            value, _kind = winreg.QueryValueEx(k, APP_NAME)
            raw = str(value).strip()
            if not raw or raw.casefold() != _command().strip().casefold():
                return False
            if not os.path.isfile(sys.executable):
                return False
            return bool(getattr(sys, "frozen", False)) or os.path.isfile(
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py"))
    except OSError:
        return False


def set_enabled(on: bool) -> tuple[bool, str]:
    """开/关自启，返回 (成功?, 给清言转述的消息)。"""
    try:
        if on:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                    winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _command())
            return True, "已设置开机自动启动 ✓（注册表 HKCU Run）"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, APP_NAME)
        except FileNotFoundError:
            pass
        return True, "已关闭开机自启"
    except OSError as e:
        return False, f"设置开机自启失败：{e}"
