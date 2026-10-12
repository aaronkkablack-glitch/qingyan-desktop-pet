"""第五轮-第三轮回归：状态仲裁单一事实来源、立绘期间记账、one-shot 瞬时事件、拖拽/唤醒回仲裁、
锚点缓存、用量条比例、zcode 崩溃残留、sticky 不被顶掉。"""
import json
import os
import shutil
import sys
import tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from pet import config as cfgmod
from pet.config import Config
from pet.pet_window import PetWindow

app = QApplication.instance() or QApplication([])
cfgmod.CONFIG_PATH = os.path.join(tempfile.mkdtemp(), "config.json")  # 不碰真实配置


def _pet():
    pet = PetWindow(Config())
    if not hasattr(pet._renderer, "set_state"):
        print("（素材缺失，跳过）")
        sys.exit(0)
    return pet


def _finish_oneshot(pet):
    """模拟 one-shot 播完：tick 足够久并处理延后的回调。"""
    pet._renderer.tick(10.0)
    app.processEvents()


def test_portrait_keeps_bookkeeping():
    pet = _pet()
    pet.request_sprite_state("thinking", "game")
    pet.set_portrait("少女.png")
    pet.request_sprite_state("idle", "game")      # 立绘期间游戏结束
    assert "game" not in pet._state_requests, "立绘期间的清除请求也要记账"
    pet.set_sprite_state("idle")                   # 菜单退出立绘
    pet._sleep_timer.timeout.emit()
    assert pet._renderer.current_state() == "sleeping", "残留 thinking 会让桌宠永不睡觉"
    pet.close()


def test_exit_portrait_reuses_sprite_renderer():
    pet = _pet()
    r0 = pet._renderer
    pet.set_portrait("少女.png")
    pet.set_sprite_state("idle")
    assert pet._renderer is r0, "退出立绘应复用原渲染器而不是重新解码全部帧"
    assert pet._renderer._oneshot_cb is not None
    pet.close()


def test_oneshot_outranked_is_dropped_and_no_stuck_done():
    pet = _pet()
    pet.request_sprite_state("thinking", "zcode")
    pet.request_sprite_state("thinking", "chat")
    pet.request_sprite_state("done", "chat")       # 被 zcode 压住：丢弃
    assert pet._renderer.current_state() == "thinking"
    assert "chat" not in pet._state_requests
    pet.request_sprite_state("done", "zcode")      # 最高来源完成：播庆祝
    assert pet._renderer.current_state() == "done"
    _finish_oneshot(pet)
    assert pet._renderer.current_state() == "idle", "播完回仲裁结果，不得卡在 done 末帧"
    assert pet._state_requests == {}
    pet.close()


def test_stale_error_not_replayed_after_game():
    pet = _pet()
    pet.request_sprite_state("thinking", "game")
    pet.request_sprite_state("error", "chat")      # 游戏期间聊天出错：被压住
    pet.request_sprite_state("idle", "game")
    assert pet._renderer.current_state() == "idle", "游戏结束后不应补播过时的出错动画"
    pet.close()


def test_drag_release_and_wake_return_to_arbitration():
    pet = _pet()
    pet.show()
    app.processEvents()
    pet.request_sprite_state("thinking", "zcode")

    def ev(kind, gx, gy, btn, btns):
        return QMouseEvent(kind, QPointF(50, 50), QPointF(gx, gy), btn, btns, Qt.NoModifier)
    pet.mousePressEvent(ev(QEvent.MouseButtonPress, 300, 300, Qt.LeftButton, Qt.LeftButton))
    pet.mouseMoveEvent(ev(QEvent.MouseMove, 360, 340, Qt.NoButton, Qt.LeftButton))
    assert pet._renderer.current_state() == "dragging"
    pet.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, 360, 340, Qt.LeftButton, Qt.NoButton))
    assert pet._renderer.current_state() == "thinking", "拖拽松开应回到 zcode 思考"
    pet.request_sprite_state("idle", "zcode")
    pet.request_sprite_state("thinking", "game")
    pet.set_sprite_state("sleeping")
    pet.activity()
    assert pet._renderer.current_state() == "thinking", "唤醒应回到仲裁结果"
    pet.close()


def test_double_click_does_not_poke_twice():
    pet = _pet()
    pet.show()
    app.processEvents()
    said = []
    pet.say = lambda text, ms=7000, sticky=False: said.append(text)

    def ev(kind, btn, btns):
        return QMouseEvent(kind, QPointF(50, 50), QPointF(300, 300), btn, btns, Qt.NoModifier)
    pet.mousePressEvent(ev(QEvent.MouseButtonPress, Qt.LeftButton, Qt.LeftButton))
    pet.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, Qt.LeftButton, Qt.NoButton))
    pet.mouseDoubleClickEvent(ev(QEvent.MouseButtonDblClick, Qt.LeftButton, Qt.LeftButton))
    pet.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, Qt.LeftButton, Qt.NoButton))
    assert len(said) == 1, said
    pet.close()


def test_listening_timer_reused():
    pet = _pet()
    t = pet._action_revert_timer
    pet._play_listening()
    pet._play_listening()
    assert pet._action_revert_timer is t and t.isActive()
    pet.set_sprite_state("thinking")               # 用户接管后旧计时器不再生效
    assert not t.isActive()
    pet.close()


def test_anchor_cache_hits():
    pet = _pet()
    pet.show()
    app.processEvents()
    a1 = pet._content_anchor()
    calls = {"n": 0}
    orig = pet._renderer.paint
    pet._renderer.paint = lambda p: (calls.__setitem__("n", calls["n"] + 1), orig(p))
    a2 = pet._content_anchor()
    assert a1 == a2 and calls["n"] == 0, "同一帧应命中缓存且不抛 TypeError"
    pet.close()


def test_sticky_not_replaced_by_normal_line():
    pet = _pet()
    pet.show()
    app.processEvents()
    pet.say("该喝水啦", 9000, sticky=True)
    pet.say("戳我干嘛～", 3000)
    assert pet.bubble._sticky and "喝水" in pet.bubble._label.text()
    pet.say("到点啦", 9000, sticky=True)           # 提醒可以替换提醒
    assert "到点" in pet.bubble._label.text()
    pet.close()


def test_sleep_config_runtime_refresh():
    pet = _pet()
    pet.cfg["idle_sleep_min"] = 0
    pet.refresh_sleep_config()
    assert not pet._sleep_timer.isActive()
    pet.cfg["idle_sleep_min"] = 2
    pet.refresh_sleep_config()
    assert pet._sleep_timer.isActive() and pet._sleep_timer.interval() == 120_000
    pet.close()


def test_usage_bar_ratio_by_tokens():
    from pet import usage_panel as up
    old = up.usage_reader.zcode_usage
    up.usage_reader.zcode_usage = lambda _p: {
        "error": "", "today": {"total": 10, "calls": 1, "cache_read": 0, "in": 5},
        "week": {"total": 100}, "total": {"total": 1000},
        "models_7d": [("big", 5, 600, 400), ("small", 50, 100, 0)]}
    try:
        panel = up.UsagePanel(Config())
        panel.refresh()
        bars = panel.findChildren(up.Bar, "modelBarTrack")
        ratios = sorted(round(b._ratio, 2) for b in bars)
        assert ratios == [0.1, 1.0], ratios
        panel.close()
    finally:
        up.usage_reader.zcode_usage = old


def test_zcode_stale_turn_cleared():
    from pet.zcode_watcher import ZcodeWatcher
    tmp = tempfile.mkdtemp()
    log = os.path.join(tmp, "zcode-2026-10-11.jsonl")
    with open(log, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event": "turn.completed"}) + "\n")   # 截断尾部的孤立 completed
        f.write(json.dumps({"event": "turn.started"}) + "\n")
    w = ZcodeWatcher(tmp, stale_sec=0.05)
    got = []
    w.state_changed.connect(got.append)
    w._stale_sec = 3600           # 基线：刚写的日志，不算陈旧
    w.start()
    w._timer.stop()
    assert got == ["thinking"], f"逐步累加夹 0：孤立 completed 不能抵消进行中的 turn {got}"
    w._stale_sec = 0.0             # 之后日志不再增长 → 视为 zcode 崩溃
    w._poll()
    assert got == ["thinking", "idle"], got
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("第五轮-第三轮回归测试通过 ✔")
