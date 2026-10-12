# -*- coding: utf-8 -*-
"""清言的本地工具集：AI 通过 function calling 调用，桌宠代为执行。

内置工具：
  open_app   打开应用（别名表 → 命令；也可给完整路径/exe 名）
  open_url   用默认浏览器打开网页
  list_apps  列出当前可一键打开的应用（供 AI 回答"你能打开什么"）
别名表在 config.json 的 app_aliases（用户可自行增删）。
安全边界：open_app 仅经 os.startfile 执行别名表命令，或扩展名为 .exe/.lnk 的路径/exe 名
（拒绝脚本、网络共享路径和相对目录）；不执行任意 shell 字符串。
"""
import os
import subprocess

from PySide6.QtCore import QObject, Signal

# 常用应用别名 → 启动命令（Windows）
DEFAULT_ALIASES = {
    "记事本": "notepad",
    "计算器": "calc",
    "画图": "mspaint",
    "任务管理器": "taskmgr",
    "文件资源管理器": "explorer",
    "资源管理器": "explorer",
    "命令行": "cmd",
    "控制面板": "control",
    "截图工具": "snippingtool",
    "运行": None,  # 占位：无
}

# open_app 直接给路径/文件名时允许的扩展名（.bat/.ps1/.vbs 等脚本不允许由模型直接执行）
APP_EXTS = (".exe", ".lnk")

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "打开本地应用程序。app 必须用别名原词或完整 exe 路径。",
            "parameters": {
                "type": "object",
                "properties": {"app": {"type": "string", "description": "应用别名或完整路径"}},
                "required": ["app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "用默认浏览器打开网页（需要网址）",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "完整网址，含 https://"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_apps",
            "description": "列出当前可一键打开的应用别名清单（用户问'你能打开什么'时调用）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_autostart",
            "description": "设置/取消清言桌宠的开机自动启动（用户说'开机自启/不要自启'时调用）",
            "parameters": {
                "type": "object",
                "properties": {"enabled": {"type": "boolean", "description": "true=开启自启"}},
                "required": ["enabled"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_water_reminder",
            "description": "修改喝水提醒设置（用户说'喝水提醒改成30分钟/关掉喝水提醒'时调用）",
            "parameters": {
                "type": "object",
                "properties": {"enabled": {"type": "boolean", "description": "开/关提醒"},
                               "interval_min": {"type": "integer", "description": "间隔分钟(5-240)"}},
            },
        },
    },
]


def tool_schemas(cfg) -> list:
    """按当前 config 动态生成 schemas：open_app 描述里嵌入全部可用别名，
    模型第一轮就知道精确名字（省一次 list_apps 往返，也避免别名大小写/叫法对不上）。"""
    import copy
    merged = dict(DEFAULT_ALIASES)
    merged.update(cfg.get("app_aliases") or {})
    names = sorted(k for k, v in merged.items() if v)
    schemas = copy.deepcopy(TOOL_SCHEMAS)
    schemas[0]["function"]["description"] = (
        "打开本地应用程序。app 必须用别名原词或完整 exe 路径。当前可用别名：" + "、".join(names))
    return schemas


class ToolHost(QObject):
    """工具执行器。result_ready = Signal(工具名, 成功?, 结果文本)"""
    result_ready = Signal(str, bool, str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.cfg = config
        self._notifier = None   # 配置被工具修改后通知（main 注入 water.restart 等）
        self._confirm = None    # 敏感操作确认钩子 fn(标题, 说明) -> bool；None = 不询问（测试 / 无界面）

    def set_notifier(self, fn):
        self._notifier = fn

    def set_confirm(self, fn):
        self._confirm = fn

    def _ask(self, title: str, text: str) -> bool:
        """模型驱动的敏感操作（开机自启、打开非别名程序）需要用户当场点头。
        白嫖通道的上游是第三方，模型输出不能被当作用户意图。"""
        if self._confirm is None:
            return True
        try:
            return bool(self._confirm(title, text))
        except Exception:
            return False   # 弹窗本身出错：按拒绝处理，安全优先

    # ---- 别名表 ----
    def aliases(self) -> dict:
        merged = dict(DEFAULT_ALIASES)
        merged.update(self.cfg.get("app_aliases") or {})
        merged = {k: v for k, v in merged.items() if v}
        return merged

    @staticmethod
    def _norm(s: str) -> str:
        return s.strip().lower()

    def _lookup(self, app: str) -> str | None:
        """别名查找：不区分大小写与首尾空格（说 chrome / Chrome 浏览器 都认 Chrome）。"""
        want = self._norm(app)
        for k, v in self.aliases().items():
            if self._norm(k) == want or want == self._norm(k) + "浏览器":
                return v
        return None

    @staticmethod
    def _start(target: str) -> tuple[bool, str]:
        """os.startfile 统一出口：展开环境变量 + 异常不逃出（否则会打断整轮工具循环）。"""
        try:
            os.startfile(os.path.expandvars(target))
            return True, ""
        except OSError as e:
            return False, str(e)

    # ---- 工具实现 ----
    def run(self, name: str, args: dict) -> tuple[bool, str]:
        if name == "open_app":
            return self._open_app(str(args.get("app", "")).strip())
        if name == "open_url":
            url = str(args.get("url", "")).strip()
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            try:
                os.startfile(url)
            except OSError as e:
                return False, f"打开网址失败：{e}"
            return True, f"已在浏览器打开 {url}"
        if name == "list_apps":
            apps = ", ".join(sorted(k for k, v in self.aliases().items() if v))
            return True, f"可一键打开的应用：{apps}；也可以直接给我完整路径"
        if name == "set_autostart":
            from .autostart import set_enabled
            want = bool(args.get("enabled"))
            if not self._ask("修改开机自启", f"清言想要{'开启' if want else '关闭'}开机自启。\n是否允许？"):
                return False, "用户拒绝了这次开机自启修改"
            return set_enabled(want)
        if name == "set_water_reminder":
            w = dict(self.cfg.get("water") or {})
            if "enabled" in args:
                w["enabled"] = bool(args["enabled"])
            if args.get("interval_min"):
                try:
                    w["interval_min"] = max(5, min(240, int(args["interval_min"])))
                except (TypeError, ValueError):
                    return False, f"间隔分钟数不对：{args['interval_min']}"
            self.cfg["water"] = w
            self.cfg.save()
            if self._notifier:
                try:
                    self._notifier()
                except Exception:
                    pass
            state = "开" if w.get("enabled") else "关"
            return True, (f"喝水提醒已更新：{state}，每 {w.get('interval_min', 45)} 分钟一次"
                          f"（{w.get('active_start', 9)}-{w.get('active_end', 22)} 点）")
        return False, f"未知工具: {name}"

    def _open_app(self, app: str) -> tuple[bool, str]:
        target = self._lookup(app)
        if target:
            ok, err = self._start(target)
            if ok:
                return True, f"已打开 {app}"
            return False, f"别名「{app}」的目标打开失败：{err}。请检查「⚙ 设置 → 应用别名」里填的路径"
        # 完整路径 / 直接 exe 名：参数来自模型输出（白嫖通道还经第三方上游），只放行程序/快捷方式。
        # 别名表是用户自己配的，不受此限制。
        low = app.lower()
        if app.startswith(("\\\\", "//")):
            return False, "出于安全考虑，不打开网络共享路径上的程序；需要的话请在「⚙ 设置 → 应用别名」里配置"
        if not low.endswith(APP_EXTS):
            if os.path.isabs(app) and os.path.exists(app):
                return False, (f"出于安全考虑，只能直接打开 {'/'.join(APP_EXTS)} 文件；"
                               "脚本等其他文件请在「⚙ 设置 → 应用别名」里配置")
            return False, f"不认识「{app}」：可以在聊天窗右上「⚙ 设置 → 应用别名」里教我认识它，或直接给我完整路径"
        if os.path.isabs(app):
            if not os.path.exists(app):
                return False, f"打开失败: 找不到 {app}"
            if not self._ask("打开程序", f"清言想要运行这个不在别名表里的程序：\n{app}\n是否允许？"):
                return False, f"用户拒绝打开 {os.path.basename(app)}"
            ok, err = self._start(app)
            return (True, f"已打开 {os.path.basename(app)}") if ok else (False, f"打开失败: {err}")
        if os.path.dirname(app):
            # 相对路径（含目录）会按当前工作目录解析，目标不可预期
            return False, "请给出完整路径（如 C:\\...\\xxx.exe），或在「⚙ 设置 → 应用别名」里配置"
        if not self._ask("打开程序", f"清言想要运行这个不在别名表里的程序：\n{app}\n是否允许？"):
            return False, f"用户拒绝打开 {app}"
        ok, err = self._start(app)   # 裸 exe 名：交给系统按 PATH / App Paths 查找
        return (True, f"已打开 {app}") if ok else (False, f"打开失败: {err}")
