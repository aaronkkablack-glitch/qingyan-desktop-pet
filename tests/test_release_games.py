"""发布第三轮：旧局结果、旧定时器、残局规则和候选一致性。"""
import os
import sys
import random
from collections import Counter
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from pet.games import xiangqi, doudizhu
from pet.games import xiangqi_engine as xe
from pet.games.doudizhu_engine import DECK, Move, parse_move, gen_moves, beats
from pet.config import Config
app = QApplication.instance() or QApplication([])

def test_stale_ai_result_does_not_unlock_new_game():
    class Window:
        _gen = 2
        _ai_busy = True
        def _pet_move(self, mv): raise AssertionError("旧着法不可执行")
    win = Window()
    xiangqi.Xiangqi._on_ai_done(win, 1, None)
    assert win._ai_busy

def test_pawn_endgame_continues():
    game = xe.Game()
    game.board = [["."]*9 for _ in range(10)]
    game.board[9][4], game.board[0][3], game.board[4][4] = "K", "k", "P"
    assert not game.is_material_draw()
    game.board[4][4] = "."
    assert game.is_material_draw()

def test_generated_cards_are_legal_and_owned():
    rng = random.Random(7301)
    for _ in range(100):
        hand = rng.sample(DECK, 20)
        for last in (Move.pass_move(), parse_move([14]), parse_move([5]*4),
                     parse_move([3]*3+[4]*3+[15,16])):
            for move in gen_moves(hand, last):
                parsed = parse_move(move.cards, last)
                assert (parsed.type, parsed.rank, parsed.length) == (move.type, move.rank, move.length)
                assert not Counter(move.cards)-Counter(hand)
                assert beats(parsed, last)
    assert not parse_move([3]*4+[4]*4).type

def test_stale_doudizhu_timer_does_not_act_on_new_game():
    w = doudizhu.create(Config())
    callbacks = []
    calls = []
    with patch.object(doudizhu.QTimer, "singleShot", side_effect=lambda ms, fn: callbacks.append(fn)):
        w._later(10, lambda: calls.append(True))
        w.new_game()
    callbacks[0]()
    assert not calls
    w.close()

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("Release game boundary tests passed")
