"""外部插件同名旁路模块隔离测试。"""
import os
import sys
import tempfile
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pet import game_plugins


def test_same_named_engine_modules_do_not_cross_load():
    root = tempfile.mkdtemp()
    old_root = game_plugins.plugin_root
    game_plugins.plugin_root = lambda: root
    first = os.path.join(root, "first")
    second = os.path.join(root, "second")
    os.makedirs(first)
    os.makedirs(second)
    open(os.path.join(first, "engine.py"), "w", encoding="utf-8").write("VALUE = 'first'\n")
    open(os.path.join(first, "plugin.py"), "w", encoding="utf-8").write(
        "from engine import VALUE\nTITLE='first'\ncreate=lambda cfg, parent=None: None\n")
    open(os.path.join(second, "engine.py"), "w", encoding="utf-8").write("VALUE = 'second'\n")
    open(os.path.join(second, "plugin.py"), "w", encoding="utf-8").write(
        "from engine import VALUE\nTITLE=VALUE\ncreate=lambda cfg, parent=None: None\n")
    try:
        first_mod = game_plugins._load(os.path.join(first, "plugin.py"), "test_first")
        second_mod = game_plugins._load(os.path.join(second, "plugin.py"), "test_second")
        assert first_mod.TITLE == "first"
        assert second_mod.TITLE == "second"
        assert "engine" not in sys.modules
    finally:
        game_plugins.plugin_root = old_root


if __name__ == "__main__":
    test_same_named_engine_modules_do_not_cross_load()
    print("插件同名模块隔离测试通过 ✔")
