"""第五轮-第四轮回归（工具/插件）：open_app 扩展名白名单、插件 sys.path 不泄漏、SystemExit 隔离、扫描缓存。"""
import os
import shutil
import sys
import tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from pet import game_plugins
import pet.tools as tools
from pet.tools import ToolHost

app = QApplication.instance() or QApplication([])


class Cfg(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)

    def save(self):
        pass


def _capture_start():
    started = []
    orig = tools.ToolHost._start
    tools.ToolHost._start = staticmethod(lambda t: (started.append(t) or True, ""))
    return started, orig


def test_open_app_rejects_scripts_unc_and_relative():
    tmp = tempfile.mkdtemp()
    bat = os.path.join(tmp, "evil.bat")
    exe = os.path.join(tmp, "ok.exe")
    for p in (bat, exe):
        open(p, "w").close()
    started, orig = _capture_start()
    try:
        h = ToolHost(Cfg(app_aliases={"脚本": bat}))
        assert h._open_app(bat)[0] is False, "模型给出的 .bat 绝对路径不得执行"
        assert h._open_app(r"\\host\share\x.exe")[0] is False, "UNC 路径不得执行"
        assert h._open_app(r"sub\x.exe")[0] is False, "相对目录不得执行"
        assert h._open_app(exe)[0] is True
        assert h._open_app("notepad.exe")[0] is True, "裸 exe 名仍交给系统查找"
        assert h._open_app("脚本")[0] is True, "用户自己配的别名不受扩展名限制"
        assert started == [exe, "notepad.exe", bat], started
    finally:
        tools.ToolHost._start = orig
        shutil.rmtree(tmp, ignore_errors=True)


def test_water_tool_bad_interval():
    h = ToolHost(Cfg(app_aliases={}, water={"enabled": True, "interval_min": 45}))
    ok, msg = h.run("set_water_reminder", {"interval_min": "abc"})
    assert ok is False and h.cfg["water"]["interval_min"] == 45


def _plugin(root, name, body, extra=None):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "plugin.py"), "w", encoding="utf-8") as f:
        f.write(body)
    for fn, src in (extra or {}).items():
        with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
            f.write(src)
    return d


def test_plugin_isolation_and_cache():
    import json as real_json
    tmp = tempfile.mkdtemp()
    old_root = game_plugins.plugin_root
    game_plugins.plugin_root = lambda: tmp
    try:
        d = _plugin(tmp, "影子", "import engine\nTITLE='影子'\nCOUNT=engine.N\n"
                    "def create(cfg, parent=None):\n    return None\n",
                    {"engine.py": "N = 1\n", "json.py": "SHADOW = True\n"})
        _plugin(tmp, "退出的", "import sys\nsys.exit(3)\n")
        found = game_plugins.discover(force=True)
        assert [p.name for p in found] == ["影子"]
        assert d not in sys.path, "插件目录加载后必须移出 sys.path"
        assert sys.modules["json"] is real_json, "插件自带 json.py 不得顶掉标准库"
        assert "退出的" in game_plugins.load_errors, "sys.exit 应被隔离并记录"
        mod_before = found[0].module
        again = game_plugins.discover()
        assert again[0].module is mod_before, "文件未变时不重复执行插件代码"
        with open(os.path.join(d, "engine.py"), "w", encoding="utf-8") as f:
            f.write("N = 22\n")
        os.utime(os.path.join(d, "engine.py"), None)
        changed = game_plugins.discover()
        assert changed[0].module is not mod_before and changed[0].module.COUNT == 22
    finally:
        game_plugins.plugin_root = old_root
        game_plugins.discover(force=True)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("第五轮-第四轮工具/插件回归测试通过 ✔")
