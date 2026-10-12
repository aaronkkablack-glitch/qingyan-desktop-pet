"""睡觉倒计时顺延测试：任意动作（含游戏/联动）与聊天活动都重置 idle 睡觉计时。
运行: python -m pytest tests/test_sleep.py -q  或 QT_QPA_PLATFORM=offscreen python tests/test_sleep.py
"""
import os
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from pet.config import Config
from pet.pet_window import PetWindow

ACC = 150   # 加速后的倒计时毫秒数


def _fresh() -> PetWindow:
    pet = PetWindow(Config())
    pet._sleep_timer.setInterval(ACC)
    pet._sleep_timer.start()
    return pet


def _restarted(pet) -> int:
    """等一会让倒计时衰减，返回当前剩余时间（供顺延前后对比）。"""
    time.sleep(0.09)
    return pet._sleep_timer.remainingTime()


def test_action_resets_timer():
    """动作/联动/外部活动三条路径都会顺延倒计时。"""
    pet = _fresh()
    # 1) 任意动作（菜单选动作路径）
    before = _restarted(pet)
    pet.set_sprite_state("thinking")
    assert pet._sleep_timer.remainingTime() > before + 30, "动作应顺延倒计时"
    # 2) 联动路径（游戏胜利欢呼 / zcode / 聊天状态 同一条 request 通道）
    before = _restarted(pet)
    pet.request_sprite_state("done")
    assert pet._sleep_timer.remainingTime() > before + 30, "联动动作应顺延倒计时"
    # 3) 外部活动钩子（聊天）
    before = _restarted(pet)
    pet.activity()
    assert pet._sleep_timer.remainingTime() > before + 30, "聊天等活动应顺延倒计时"
    pet.close()


def test_sleep_still_triggers_when_idle():
    """无任何活动时倒计时照常走完进入睡觉（顺延不等于取消）。"""
    pet = _fresh()
    assert pet._sleep_timer.remainingTime() > 0
    pet._sleep_timer.timeout.emit()          # 模拟倒计时到期
    assert pet._renderer.current_state() == "sleeping", "闲置到期应进入睡觉"
    pet.activity()                            # 活动唤醒
    assert pet._renderer.current_state() == "idle"
    pet.close()


def test_chat_activity_hook():
    """聊天活动钩子：打字 / 发送 / 收到流式内容三条路径都触发。"""
    import tempfile
    from PySide6.QtCore import QObject, Signal, QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from pet import chat_panel as cp

    class _Cfg(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)
        def save(self):
            pass

    class _Glm(QObject):
        thinking_started = Signal(); chunk = Signal(str)
        finished = Signal(str, dict); failed = Signal(str)
        tool_calls_finished = Signal(list)
        busy = False
        def send(self, *a, **k):
            pass

    class _Store:
        def summary_for(self, now):
            return "无"

    old_hist = cp.HISTORY_PATH
    cp.HISTORY_PATH = os.path.join(tempfile.mkdtemp(), "chat_history.json")
    try:
        cfg = _Cfg(api_key="k", api_base="x", chat_models=["m"], chat_model="m",
                   max_history_messages=20, app_aliases={})
        panel = cp.ChatPanel(cfg, _Glm(), _Store())
        calls = []
        panel.set_activity_hook(lambda: calls.append(1))
        ev = QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier, "a")
        panel.eventFilter(panel.input, ev)
        assert len(calls) == 1, "输入框打字应触发活动"
        panel._on_chunk("hi")
        assert len(calls) == 2, "流式内容应触发活动"
        panel.input.setPlainText("你好")
        panel.send()
        assert len(calls) == 3, "发送消息应触发活动"
    finally:
        cp.HISTORY_PATH = old_hist


def test_state_sources_are_prioritized_and_cleared_independently():
    """游戏状态优先于 zcode；清除游戏后恢复 zcode，不被 idle 互相覆盖。"""
    pet = _fresh()
    pet.request_sprite_state("thinking", "zcode")
    assert pet._renderer.current_state() == "thinking"
    pet.request_sprite_state("done", "game")
    assert pet._renderer.current_state() == "done"
    pet.request_sprite_state("idle", "game")
    assert pet._renderer.current_state() == "thinking"
    pet.request_sprite_state("idle", "zcode")
    assert pet._renderer.current_state() == "idle"
    pet.close()


def test_working_state_does_not_enter_sleep_on_timeout():
    """聊天/游戏思考中睡眠计时到期只顺延，不切到 sleeping。"""
    pet = _fresh()
    pet.request_sprite_state("thinking", "chat")
    pet._sleep_timer.timeout.emit()
    assert pet._renderer.current_state() == "thinking"
    pet.request_sprite_state("idle", "chat")
    pet._sleep_timer.timeout.emit()
    assert pet._renderer.current_state() == "sleeping"
    pet.close()


if __name__ == "__main__":
    test_action_resets_timer()
    test_sleep_still_triggers_when_idle()
    test_chat_activity_hook()
    test_state_sources_are_prioritized_and_cleared_independently()
    test_working_state_does_not_enter_sleep_on_timeout()
    print("睡觉顺延测试通过 ✔")
