"""第八轮游戏规则与用户体验回归。"""
import json
import os
import sys
import tempfile
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.games.doudizhu_engine import parse_move
from pet.games.xiangqi_engine import Game

app = QApplication.instance() or QApplication([])


def test_doudizhu_airplane_wings_and_jokers():
    assert parse_move([3, 3, 3, 4, 4, 4, 9, 10]).type == "plane1"
    assert parse_move([3, 3, 3, 4, 4, 4, 16, 17]).type == ""
    assert parse_move([3, 3, 3, 4, 4, 4, 9, 9, 10, 10]).type == "plane2"


def test_xiangqi_repeat_count_includes_current_position():
    game = Game()
    key = game.pos_key()
    game.hist = [key, key]
    assert game.repeat_count() == 3


def test_xiangqi_material_draw_contract():
    """当前引擎采用无车马炮且兵不超过一枚的实用和棋近似。"""
    game = Game()
    game.board = [row[:] for row in game.board]
    for r in range(10):
        for c in range(9):
            if game.board[r][c] not in ("K", "k"):
                game.board[r][c] = "."
    game.board[5][0] = "P"
    assert game.is_material_draw() is False


def test_avatar_cancel_keeps_existing_file():
    from pet import settings_dialog as sd
    from pet.settings_dialog import SettingsDialog
    tmp = tempfile.mkdtemp()
    old_data = sd.DATA_DIR
    sd.DATA_DIR = tmp
    try:
        path = os.path.join(tmp, "user_avatar.png")
        open(path, "wb").write(b"old")
        cfg = Config()
        dlg = SettingsDialog(cfg)
        dlg._reset_avatar()
        dlg.reject()
        assert os.path.exists(path), "取消头像设置不得删除原头像"
    finally:
        sd.DATA_DIR = old_data


if __name__ == "__main__":
    test_doudizhu_airplane_wings_and_jokers()
    test_xiangqi_repeat_count_includes_current_position()
    test_xiangqi_material_draw_contract()
    test_avatar_cancel_keeps_existing_file()
    print("第八轮游戏与体验测试通过 ✔")
