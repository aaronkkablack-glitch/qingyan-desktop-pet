"""复核后加固：judge 超时、--release-check 隔离、模型驱动敏感操作确认、白嫖隐私确认。"""
import os
import subprocess
import sys
import tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])


def test_judge_timeout_becomes_runtimeerror_after_one_retry():
    from pet import xiangqi_rules as xr
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise subprocess.TimeoutExpired("judge", 3)

    orig = xr.subprocess.run
    xr.subprocess.run = boom
    try:
        try:
            xr.judge("4k4/9/9/9/9/9/9/9/9/3K5 w - - 0 1", [])
        except RuntimeError as e:
            assert "超时" in str(e)
        else:
            raise AssertionError("超时必须转成 RuntimeError（TimeoutExpired 不会被棋局捕获）")
        assert len(calls) == 2, "应重试一次"
    finally:
        xr.subprocess.run = orig


def test_judge_recovers_after_one_transient_failure():
    from pet import xiangqi_rules as xr
    orig = xr.subprocess.run
    state = {"n": 0}

    def flaky(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise subprocess.TimeoutExpired("judge", 3)
        return orig(*a, **k)

    xr.subprocess.run = flaky
    try:
        assert xr.judge("4k4/9/9/9/9/9/9/9/9/R2K5 w - - 0 1", []) == "ongoing"
    finally:
        xr.subprocess.run = orig


def test_xiangqi_game_survives_judge_failure():
    from pet.config import Config
    from pet.games import xiangqi
    from pet.games.xiangqi_engine import RED
    import pet.xiangqi_rules as xr
    w = xiangqi.create(Config())
    orig = xr.game_result
    xr.game_result = lambda g: (_ for _ in ()).throw(RuntimeError("规则裁决超时"))
    try:
        w.player_move(w.game.legal_moves(RED)[0])
        assert not w.over, "judge 失败不能把整局判死"
        assert w._rules_warned
    finally:
        xr.game_result = orig
        w.close()


def test_release_check_refuses_outside_isolation():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {k: v for k, v in os.environ.items() if k != "QINGYAN_RELEASE_CHECK_ISOLATED"}
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    out = os.path.join(tempfile.mkdtemp(), "r.json")
    cfg = os.path.join(root, "config.json")
    before = os.path.getmtime(cfg) if os.path.exists(cfg) else None
    r = subprocess.run([sys.executable, "main.py", "--release-check", out], cwd=root, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 2 and "拒绝运行" in r.stderr, (r.returncode, r.stderr[-200:])
    assert not os.path.exists(out)
    assert (os.path.getmtime(cfg) if os.path.exists(cfg) else None) == before, "被拒绝时不得改写真实配置"
    # 设了环境变量但目录不在临时目录下，同样拒绝
    env["QINGYAN_RELEASE_CHECK_ISOLATED"] = "1"
    # 不依赖仓库实际位置：CI/审查可能将源码clone到临时目录。
    script = ("from unittest.mock import patch; from pet.release_check import _require_isolation; "
              "\nwith patch('pet.release_check._under_temp', return_value=False):\n _require_isolation()")
    r = subprocess.run([sys.executable, "-c", script], cwd=root, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 2, "非隔离位置即使有环境变量也必须拒绝"


def test_sensitive_tools_require_confirmation():
    from pet import tools
    from pet.tools import ToolHost

    class Cfg(dict):
        def save(self):
            pass

    started = []
    orig = ToolHost._start
    ToolHost._start = staticmethod(lambda t: (started.append(t) or True, ""))
    import pet.autostart as au
    set_calls = []
    orig_set = au.set_enabled
    au.set_enabled = lambda v: (set_calls.append(v) or True, "ok")
    try:
        h = ToolHost(Cfg(app_aliases={}))
        asked = []
        h.set_confirm(lambda title, text: (asked.append(title) or False))
        ok, msg = h.run("open_app", {"app": "calc.exe"})
        assert not ok and not started and "拒绝" in msg
        ok, msg = h.run("set_autostart", {"enabled": True})
        assert not ok and not set_calls and "拒绝" in msg
        assert len(asked) == 2
        h.set_confirm(lambda title, text: True)
        assert h.run("open_app", {"app": "calc.exe"})[0] and started == ["calc.exe"]
        assert h.run("set_autostart", {"enabled": True})[0] and set_calls == [True]
        # 弹窗本身抛异常 → 按拒绝处理
        h.set_confirm(lambda *_: 1 / 0)
        started.clear()
        assert not h.run("open_app", {"app": "calc.exe"})[0] and not started
        # 别名表里的应用（用户自己配的）不弹窗
        h2 = ToolHost(Cfg(app_aliases={"计算器": "calc.exe"}))
        h2.set_confirm(lambda *_: (_ for _ in ()).throw(AssertionError("别名不应弹窗")))
        assert h2.run("open_app", {"app": "计算器"})[0]
    finally:
        ToolHost._start = orig
        au.set_enabled = orig_set


def test_freelane_privacy_confirm_gates_first_enable():
    from pet import config as cfgmod
    cfgmod.CONFIG_PATH = os.path.join(tempfile.mkdtemp(), "config.json")
    cfgmod.DATA_DIR = tempfile.mkdtemp()
    from pet.config import Config
    from pet.settings_dialog import SettingsDialog
    cfg = Config()
    cfg["api_key"] = "k"
    cfg["freelane"] = {"enabled": False}
    dlg = SettingsDialog(cfg)
    dlg.chan_freelane.setChecked(True)
    dlg._confirm_freelane_privacy = lambda: False
    dlg._save()
    assert not cfg["freelane"].get("enabled"), "拒绝隐私确认后不得切换通道"
    assert cfg["api_key"] == "k"
    dlg._confirm_freelane_privacy = lambda: True
    dlg._save()
    assert cfg["freelane"].get("enabled") and cfg["api_key"] == "freelane"
    # 已经启用后再保存设置：不重复询问
    dlg2 = SettingsDialog(cfg)
    dlg2._confirm_freelane_privacy = lambda: (_ for _ in ()).throw(AssertionError("不应重复询问"))
    dlg2._save()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("第九轮加固测试通过 ✔")
