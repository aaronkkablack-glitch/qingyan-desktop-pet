"""气泡 sticky 行为测试：常驻提醒不自动消失；云朵不被上一条 sticky 污染。
运行: python -m pytest tests/test_bubble.py -q  或 QT_QPA_PLATFORM=offscreen python tests/test_bubble.py
"""
import os
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from pet.bubble import BubbleWidget

app = QApplication.instance() or QApplication([])


def test_sticky_no_auto_dismiss():
    """sticky 气泡：不启动消失定时器；dismiss 才关闭。"""
    b = BubbleWidget()
    b.say("该喝水啦", (200, 200), 7000, sticky=True)
    assert b._sticky is True
    assert not b._timer.isActive(), "sticky 气泡不得启动自动消失定时器"
    assert b.isVisible()
    b.dismiss()
    assert not b.isVisible()


def test_cloud_clears_sticky():
    """sticky 提醒显示期间长按出云朵：云朵可点按关闭且仍会自动消失。"""
    from PySide6.QtCore import Qt
    b = BubbleWidget()
    b.say("日程提醒", (200, 200), 9000, sticky=True)
    assert b._sticky and not b._timer.isActive()
    b.cloud_say("现在是12:00", (200, 200), 5000)
    assert b._sticky is False, "云朵必须清除 sticky 状态"
    assert not b.testAttribute(Qt.WA_TransparentForMouseEvents), "长按云朵应允许点按关闭"
    assert not (b.windowFlags() & Qt.WindowTransparentForInput), "云朵窗口不得保持输入穿透标志"
    assert b._timer.isActive(), "云朵应启动自动消失定时器"


def test_cloud_click_dismisses():
    """长按呼出的日程/报时云朵，点按后应立即关闭。"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    b = BubbleWidget()
    b.cloud_say("现在是12:00，下一场课程是数学", (200, 200), 5000)
    assert b.isVisible()
    b.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(20, 20),
                                  QPointF(20, 20), Qt.LeftButton, Qt.LeftButton,
                                  Qt.NoModifier))
    assert not b.isVisible(), "点按长按云朵应关闭气泡"


def test_normal_say_replaces_sticky():
    """普通气泡（如单击台词）替换 sticky 后恢复自动消失。"""
    b = BubbleWidget()
    b.say("常驻提醒", (200, 200), 9000, sticky=True)
    b.say("在呢在呢！", (200, 200), 3000)
    assert b._sticky is False
    assert b._timer.isActive()




def test_bubble_follows_pet_drag():
    """拖动清言：气泡按相同位移跟随（不再被落下），且不被屏幕钳制破坏相对位。"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from pet.config import Config
    from pet.pet_window import PetWindow

    pet = PetWindow(Config())
    pet.show()
    app.processEvents()
    pet.move(300, 260)
    app.processEvents()
    pet.say("测试气泡", 5000)
    assert pet.bubble.isVisible()
    b0, p0 = pet.bubble.pos(), pet.pos()

    def press(gx, gy):
        pet.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(50, 50),
                                        QPointF(gx, gy), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

    def move(gx, gy):
        pet.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(50, 50),
                                       QPointF(gx, gy), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))

    def release(gx, gy):
        pet.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(50, 50),
                                          QPointF(gx, gy), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))

    press(p0.x() + 50, p0.y() + 50)
    move(p0.x() + 130, p0.y() + 120)        # 桌宠位移 (80, 70)
    release(p0.x() + 130, p0.y() + 120)
    moved = pet.pos() - p0
    assert (moved.x(), moved.y()) == (80, 70), f"桌宠拖动异常 {moved}"
    assert pet.bubble.isVisible(), "拖动后气泡不应消失"
    bd = pet.bubble.pos() - b0
    assert (bd.x(), bd.y()) == (80, 70), f"气泡应同步位移 {moved}，实际 {bd}"
    pet.close()


def test_bubble_sync_helper_scurry_path():
    """_sync_bubble 独立路径（乱跑彩蛋 valueChanged 走它）：位移跟随正确。"""
    from PySide6.QtCore import QPoint
    from pet.config import Config
    from pet.pet_window import PetWindow

    pet = PetWindow(Config())
    pet.show()
    app.processEvents()
    pet.move(260, 240)
    app.processEvents()
    pet.say("跟随测试", 5000)
    b0 = pet.bubble.pos()
    pet.move(pet.pos() + QPoint(40, 25))
    pet._sync_bubble()
    bd = pet.bubble.pos() - b0
    assert (bd.x(), bd.y()) == (40, 25), f"乱跑路径跟随异常 {bd}"
    pet.close()




def test_sticky_first_click_only_dismisses():
    """确认式气泡：首次点清言只关气泡，不触发戳一戳台词/动作；再点恢复正常。"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from pet.config import Config
    from pet.pet_window import PetWindow

    pet = PetWindow(Config())
    pet.show()
    app.processEvents()

    def press(btn=Qt.LeftButton):
        pet.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(50, 50),
                                        QPointF(300, 300), btn, btn, Qt.NoModifier))

    def release(btn=Qt.LeftButton):
        pet.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(50, 50),
                                          QPointF(300, 300), btn, Qt.NoButton, Qt.NoModifier))

    pet.say("该喝水啦", 9000, sticky=True)
    assert pet.bubble.isVisible() and pet.bubble._sticky
    state_before = pet._renderer.current_state() if hasattr(pet._renderer, "current_state") else None
    press(); release()
    assert not pet.bubble.isVisible(), "首次点击应关闭气泡"
    if state_before is not None:
        assert pet._renderer.current_state() == state_before, "首次点击不得触发聆听等动作"
    assert not pet.bubble.isVisible()
    # 第二次点击：无 sticky 了 → 正常戳一戳（台词气泡出现）
    press(); release()
    assert pet.bubble.isVisible() and not pet.bubble._sticky, "再次点击应正常出台词气泡"
    pet.close()


def test_sticky_first_click_does_not_wake_sleeping_pet():
    """睡觉时首次点确认气泡只关闭显示，不唤醒或改变动作状态。"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from pet.config import Config
    from pet.pet_window import PetWindow

    pet = PetWindow(Config())
    pet.show()
    app.processEvents()
    pet.set_sprite_state("sleeping")
    pet.say("该喝水啦", 9000, sticky=True)
    pet.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(50, 50),
                                    QPointF(300, 300), Qt.LeftButton, Qt.LeftButton,
                                    Qt.NoModifier))
    pet.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(50, 50),
                                      QPointF(300, 300), Qt.LeftButton, Qt.NoButton,
                                      Qt.NoModifier))
    assert not pet.bubble.isVisible()
    assert pet._renderer.current_state() == "sleeping", "确认气泡首次点击不得唤醒睡觉动作"
    pet.close()


if __name__ == "__main__":
    test_sticky_no_auto_dismiss()
    test_cloud_clears_sticky()
    test_cloud_click_dismisses()
    test_normal_say_replaces_sticky()
    test_bubble_follows_pet_drag()
    test_bubble_sync_helper_scurry_path()
    test_sticky_first_click_only_dismisses()
    test_sticky_first_click_does_not_wake_sleeping_pet()
    print("气泡 sticky 行为测试通过 ✔")
