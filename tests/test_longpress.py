"""长按/单击交互测试：长按云朵不被松开时的单击台词顶掉；快按仍出台词。
运行: python -m pytest tests/test_longpress.py -q  或 QT_QPA_PLATFORM=offscreen python tests/test_longpress.py
"""
import os
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.pet_window import PetWindow

app = QApplication.instance() or QApplication([])

CLOUD_TEXT = "现在是12:00，应该午休啦，主人~"


def make_pet():
    pet = PetWindow(Config())
    pet.set_status_provider(lambda: CLOUD_TEXT)
    return pet


def _press(pet, btn=Qt.LeftButton):
    pet.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(50, 50),
                                    QPointF(150, 150), btn, btn, Qt.NoModifier))


def _release(pet, btn=Qt.LeftButton):
    pet.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(50, 50),
                                      QPointF(150, 150), btn, Qt.NoButton, Qt.NoModifier))


def test_longpress_release_does_not_poke():
    """长按出云朵后松开：云朵仍在，不弹单击台词。"""
    pet = make_pet()
    _press(pet)
    pet._on_hover_report()          # 模拟 700ms 计时到（云朵弹出）
    assert pet.bubble._cloud and pet.bubble._label.text() == CLOUD_TEXT
    _release(pet)                   # 松开——此前 bug：这里会弹台词顶掉云朵
    assert pet.bubble._cloud, "松开不得触发台词气泡"
    assert pet.bubble._label.text() == CLOUD_TEXT, "云朵应保留"


def test_quick_click_still_pokes():
    """快按快放（未到 700ms）：正常出单击台词。"""
    pet = make_pet()
    _press(pet)
    _release(pet)
    assert not pet.bubble._cloud, "快按应出普通台词气泡"
    assert pet.bubble._label.text(), "台词气泡应有内容"


def test_longpress_without_provider_no_poke():
    """无报时文案（provider 返回空）时长按触发过，松开同样不出台词。"""
    pet = make_pet()
    pet.set_status_provider(lambda: None)
    _press(pet)
    pet._on_hover_report()
    assert not pet.bubble.isVisible()  # 无文案不出云朵
    _release(pet)
    assert not pet.bubble.isVisible(), "长按触发过（哪怕无云朵）松开也不得弹台词"


if __name__ == "__main__":
    test_longpress_release_does_not_poke()
    test_quick_click_still_pokes()
    test_longpress_without_provider_no_poke()
    print("长按交互测试通过 ✔")
