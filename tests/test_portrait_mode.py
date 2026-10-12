"""立绘模式防打断测试：自动联动源（request_sprite_state）不得打断立绘，
用户菜单出口（set_sprite_state）仍可退出立绘。
运行: python -m pytest tests/test_portrait_mode.py -q  或 QT_QPA_PLATFORM=offscreen python tests/test_portrait_mode.py
"""
import os
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.pet_window import PetWindow

app = QApplication.instance() or QApplication([])


def _pet():
    return PetWindow(Config())


def test_auto_sources_do_not_break_portrait():
    """zcode 联动 / 聊天三信号 / one-shot 回 idle 全走 request：立绘下全部被忽略。"""
    pet = _pet()
    pet.set_portrait("少女.png")
    assert pet._portrait_mode is True
    assert not hasattr(pet._renderer, "set_state")  # StaticRenderer 立绘
    for s in ("thinking", "done", "error", "idle", "sleeping", "dragging"):
        pet.request_sprite_state(s)
        assert pet._portrait_mode is True, f"request({s}) 打断了立绘模式"
        assert not hasattr(pet._renderer, "set_state"), f"request({s}) 重建了动画渲染器"


def test_menu_exit_still_works():
    """菜单"🎭 动作"（set_sprite_state）= 退出立绘的唯一出口，必须仍然有效。"""
    pet = _pet()
    pet.set_portrait("少女.png")
    pet.set_sprite_state("idle")
    assert pet._portrait_mode is False
    assert hasattr(pet._renderer, "set_state")
    assert pet._renderer.current_state() == "idle"


def test_revert_timer_race():
    """动画模式单击播 recording，4s 回 idle 定时器存活期间切立绘 → 到期不得打断立绘。"""
    pet = _pet()
    if not hasattr(pet._renderer, "set_state"):
        return  # 素材缺失回退静态渲染时无此路径
    pet._play_listening()
    assert pet._renderer.current_state() == "recording"
    pet.set_portrait("少女.png")
    pet._action_revert_timer.timeout.emit()  # 模拟定时器到期
    assert pet._portrait_mode is True, "回 idle 定时器到期打断了立绘模式"
    assert not hasattr(pet._renderer, "set_state")


def test_oneshot_callback_reattached_after_exit_portrait():
    """从立绘退回动画后，重建的渲染器必须仍带 one-shot 回调（done/error 播完能回 idle）。"""
    pet = _pet()
    pet.set_portrait("少女.png")
    pet.set_sprite_state("done")
    assert hasattr(pet._renderer, "set_state")
    assert pet._renderer._oneshot_cb is not None, "重建的渲染器丢失了 one-shot 回调"


if __name__ == "__main__":
    test_auto_sources_do_not_break_portrait()
    test_menu_exit_still_works()
    test_revert_timer_race()
    test_oneshot_callback_reattached_after_exit_portrait()
    print("立绘模式防打断测试通过 ✔")
