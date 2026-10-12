"""源码版/打包版运行边界测试，不启动真实桌宠、不修改用户数据。"""
import os
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_source_and_dist_runtime_contracts():
    from pet import config, game_plugins

    assert Path(config.CONFIG_PATH) == ROOT / "config.json"
    assert Path(config.DATA_DIR) == ROOT / "data"
    assert (ROOT / "assets").is_dir()
    assert (ROOT / "GLM形象参考图" / "成女头像.png").is_file()
    assert (ROOT / "互动插件").is_dir()

    old_frozen = getattr(sys, "frozen", None)
    old_executable = sys.executable
    try:
        sys.frozen = True
        sys.executable = str(ROOT / "dist" / "清言V1.0.exe")
        assert Path(game_plugins.plugin_root()) == ROOT / "dist" / "互动插件"
    finally:
        if old_frozen is None:
            delattr(sys, "frozen")
        else:
            sys.frozen = old_frozen
        sys.executable = old_executable

    # 本测试验证路径契约；干净clone没有dist和用户数据。
    # 实际exe资源/持久化检查由隔离--release-check负责，不能要求开发者已运行过exe。


def test_single_instance_lock_contract():
    from PySide6.QtCore import QLockFile

    path = Path(tempfile.mkdtemp()) / "清言-test.lock"
    first = QLockFile(str(path))
    second = QLockFile(str(path))
    assert first.tryLock(200)
    try:
        assert not second.tryLock(200), "同一路径的第二个实例必须被锁拒绝"
    finally:
        first.unlock()
        second.unlock()


if __name__ == "__main__":
    test_source_and_dist_runtime_contracts()
    test_single_instance_lock_contract()
    print("源码/exe 运行边界测试通过 ✔")
