"""自动化收尾：搜索截止/取消和Sway尺寸缓存。"""
import os
import sys
import time
import copy
import threading
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from pet.games.xiangqi_engine import Game, ai_move
from pet.animation import SwayRenderer
app = QApplication.instance() or QApplication([])

def test_search_cancel_and_deadline_restore_board():
    game = Game()
    original = copy.deepcopy(game.board), game.turn
    started = time.monotonic()
    move = ai_move(game, 2, time_limit=0.03)
    assert time.monotonic()-started < 0.5
    assert move in game.legal_moves(game.turn)
    assert (game.board, game.turn) == original
    cancel = threading.Event()
    cancel.set()
    assert ai_move(game, 2, cancel=cancel) is None
    assert (game.board, game.turn) == original

def test_sway_resize_invalidates_cached_frame():
    renderer = SwayRenderer("shao_nv")
    renderer.set_size(80,100,1)
    first = renderer._frame()
    assert renderer._frame() is first
    renderer.set_size(160,200,1)
    assert renderer._frame().shape[:2] == (200,160)

if __name__ == "__main__":
    test_search_cancel_and_deadline_restore_board()
    test_sway_resize_invalidates_cached_frame()
    print("Cleanup tests passed")
