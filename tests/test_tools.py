"""工具别名匹配与容错测试：大小写归一 / 环境变量 / 失败不抛异常 / 动态 schema。
运行: python -m pytest tests/test_tools.py -q  或 QT_QPA_PLATFORM=offscreen python tests/test_tools.py
"""
import os
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from pet.tools import ToolHost, tool_schemas

app = QApplication.instance() or QApplication([])


class Cfg(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)

    def save(self):
        pass


def host(aliases=None):
    return ToolHost(Cfg(app_aliases=aliases or {}))


def test_alias_case_insensitive_and_trim():
    """用户存 Chrome，说 chrome / Chrome 浏览器 / 带空格 都能命中（修"不认识"根因）。"""
    h = host({"Chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe"})
    path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    assert h._lookup("Chrome") == path
    assert h._lookup("chrome") == path, "小写变体必须命中"
    assert h._lookup("  Chrome ") == path, "首尾空格必须命中"
    assert h._lookup("chrome浏览器") == path, "「别名+浏览器」叫法必须命中"
    assert h._lookup("不存在的") is None


def test_bad_target_returns_false_not_raise():
    """目标无效时返回 (False, 原因)，绝不抛异常打断工具循环。"""
    h = host({"坏路径": r"C:\不存在\definitely_missing.exe"})
    ok, msg = h._open_app("坏路径")
    assert ok is False
    assert "打开失败" in msg


def test_bad_url_returns_false_not_raise(monkeypatch=None):
    """浏览器启动失败时返回工具错误，不向 agent 链路抛异常。"""
    import pet.tools as tools
    original = tools.os.startfile
    try:
        tools.os.startfile = lambda _url: (_ for _ in ()).throw(OSError("打不开"))
        ok, msg = host().run("open_url", {"url": "https://example.com"})
        assert ok is False and "打开网址失败" in msg
    finally:
        tools.os.startfile = original


def test_lookup_supports_default_aliases():
    h = host()
    assert h._lookup("记事本") == "notepad"
    assert h._lookup("记事本浏览器") == "notepad"  # 「别名+浏览器」后缀规则对中英别名一致生效


def test_tool_schemas_embeds_aliases():
    """动态 schema 把当前别名写进 open_app 描述，模型第一轮就知道精确名字。"""
    cfg = Cfg(app_aliases={"Chrome": "x.exe"})
    schemas = tool_schemas(cfg)
    desc = schemas[0]["function"]["description"]
    assert "Chrome" in desc and "记事本" in desc, "自定义与默认别名都应嵌入描述"


def test_set_water_reminder_tool():
    """清言改喝水提醒：cfg 更新 + notifier 触发 + 范围钳制。"""
    called = {"n": 0}
    h = ToolHost(Cfg(app_aliases={}, water={"enabled": True, "interval_min": 45,
                                            "active_start": 9, "active_end": 22}))
    h.set_notifier(lambda: called.__setitem__("n", called["n"] + 1))
    ok, msg = h.run("set_water_reminder", {"enabled": True, "interval_min": 999})
    assert ok
    assert h.cfg["water"]["interval_min"] == 240, "超范围间隔应钳制到 240"
    assert called["n"] == 1, "notifier 应被调用（water.restart 即时生效）"
    ok, msg = h.run("set_water_reminder", {"enabled": False})
    assert ok and h.cfg["water"]["enabled"] is False
    assert called["n"] == 2
    assert "关" in msg


def test_autostart_roundtrip():
    """自启注册表读写往返（测试前保存原状态，结束还原）。"""
    from pet import autostart
    was = autostart.is_enabled()
    try:
        ok, _ = autostart.set_enabled(True)
        assert ok and autostart.is_enabled()
        ok, _ = autostart.set_enabled(False)
        assert ok and not autostart.is_enabled()
        # 工具路径
        h = ToolHost(Cfg(app_aliases={}))
        ok, msg = h.run("set_autostart", {"enabled": True})
        assert ok and autostart.is_enabled() and "开机" in msg
    finally:
        autostart.set_enabled(was)  # 还原用户原状


if __name__ == "__main__":
    test_alias_case_insensitive_and_trim()
    test_bad_target_returns_false_not_raise()
    test_bad_url_returns_false_not_raise()
    test_lookup_supports_default_aliases()
    test_tool_schemas_embeds_aliases()
    test_set_water_reminder_tool()
    test_autostart_roundtrip()
    print("工具别名+设置工具测试通过 ✔")
