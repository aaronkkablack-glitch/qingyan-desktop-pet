"""第五轮 R4 游戏修复回归：斗地主提示/炸弹生成、象棋新局悔棋/置换表轮走方、五子棋/井字棋 AI 定时器。
运行: QT_QPA_PLATFORM=offscreen python tests/test_round5_r4_games.py
"""
import os
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from pet.config import Config
from pet.games import doudizhu, gomoku, tictactoe, xiangqi
from pet.games import xiangqi_engine as xe
from pet.games.doudizhu_engine import Move, ai_follow, beats, gen_moves, parse_move


class _Ev:
    """伪造鼠标事件：只需 position().toPoint()。"""
    def __init__(self, x, y):
        from PySide6.QtCore import QPointF
        self._p = QPointF(x, y)

    def position(self):
        return self._p


def test_doudizhu_hint_no_import_error():
    """提示按钮：此前 `from engine import ...` 必抛 ModuleNotFoundError。"""
    w = doudizhu.create(Config())
    w._apply_bid(0, 3)                        # 玩家当地主，自由出牌
    assert w.phase == "play" and w.turn == 0
    w._on_btn("hint")
    assert w.selected, "自由出牌时提示应选中一手牌"
    # 跟牌提示
    w.selected = set()
    w.last_move, w.last_owner = parse_move([3]), 1
    w._hint()
    w.close()


def test_doudizhu_gen_moves_bombs_when_following():
    """跟牌时炸弹/王炸必须进候选；王炸能压炸弹；被压牌型无同型时 AI 会择机炸。"""
    hand = [5, 5, 5, 5, 16, 17, 3]
    moves = gen_moves(hand, parse_move([14]))
    types = {m.type for m in moves}
    assert "bomb" in types and "rocket" in types, types
    assert all(beats(m, parse_move([14])) for m in moves)
    # 王炸压炸弹
    mv = gen_moves([16, 17, 3], parse_move([9, 9, 9, 9]))
    assert [m.type for m in mv] == ["rocket"], mv
    # 小炸压不住大炸
    assert all(m.type != "bomb" for m in gen_moves([5, 5, 5, 5], parse_move([9, 9, 9, 9])))
    # AI：有普通牌可压时不炸
    m = ai_follow([5, 5, 5, 5, 15, 3], parse_move([14]), False, 17, 17)
    assert m.type == "single" and m.rank == 15
    # AI：压不住、敌人快走完时炸
    m = ai_follow([5, 5, 5, 5, 3], parse_move([14, 14]), False, 17, 3)
    assert m.type == "bomb", m
    # AI：敌人牌多且上一手不大时不轻易炸
    m = ai_follow([5, 5, 5, 5, 3], parse_move([12, 12]), False, 17, 15)
    assert m.is_pass
    # 队友出牌不炸
    assert ai_follow([5, 5, 5, 5, 3], parse_move([14, 14]), True, 10, 3).is_pass


def test_xiangqi_new_game_clears_move_log():
    """再来一局后悔棋不得操作新棋盘（此前旧 move_log 残留 → 棋盘错乱/IndexError）。"""
    w = xiangqi.create(Config())
    w.player_move(w.game.legal_moves(xe.RED)[0])
    w._pet_move()
    assert len(w.move_log) == 2 and w.undo_btn.isEnabled()
    w._finish(xe.RED)
    w.new_game()
    assert w.move_log == []
    assert not w.undo_btn.isEnabled()
    assert "轮到你" in w.status.text()
    fresh = [row[:] for row in xe.INIT_BOARD]
    w.undo()                                  # 不应抛异常也不应改棋盘
    assert w.game.board == fresh
    w.close()


def test_xiangqi_zobrist_side_to_move():
    """搜索键含轮走方：同一棋盘红走/黑走键不同；make/unmake 后键与重算一致。"""
    g = xe.Game()
    k_red = g.zkey
    g.turn = xe.BLACK
    assert g.compute_zkey() != k_red, "轮走方不同的同一棋盘不能共用置换表键"
    g.turn = xe.RED
    assert g.compute_zkey() == k_red
    for _ in range(6):
        mv = g.legal_moves(g.turn)[0]
        g.make(mv)
        assert g.zkey == g.compute_zkey(), "增量键应与从头重算一致"
    # 走一步再走回（马出马回）：棋盘相同但轮走方相反，键必须不同
    g2 = xe.Game()
    k0 = g2.zkey
    c1 = g2.make(((9, 1), (7, 2)))
    c2 = g2.make(((0, 1), (2, 2)))
    c3 = g2.make(((7, 2), (9, 1)))
    assert g2.zkey != k0, "棋盘复原但轮到黑方，键必须不同"
    g2.unmake(((7, 2), (9, 1)), c3); g2.unmake(((0, 1), (2, 2)), c2); g2.unmake(((9, 1), (7, 2)), c1)
    assert g2.zkey == k0
    # pos_key 仍含轮走方
    g3 = xe.Game()
    p_red = g3.pos_key()
    g3.turn = xe.BLACK
    assert g3.pos_key() != p_red


def test_xiangqi_tt_bounded():
    """置换表有上限：超过 TT_MAX 时 ai_move 清空；新局也清空。"""
    xe.TT.clear()
    for i in range(xe.TT_MAX + 1):
        xe.TT[-i - 1] = (0, xe.TT_EXACT, 0)
    xe.ai_move(xe.Game(), 0)
    assert len(xe.TT) < xe.TT_MAX
    w = xiangqi.create(Config())
    xe.TT[-1] = (0, xe.TT_EXACT, 0)
    w.new_game()
    assert len(xe.TT) == 0
    w.close()


def _gomoku_click(w, gx, gy):
    w._click(_Ev(w.canvas.pad + gx * w.CELL, w.canvas.pad + gy * w.CELL))


def _stones(board, ch):
    return sum(1 for row in board for c in row if c == ch)


def test_gomoku_lock_and_stale_timer():
    """思考中连点只落一子；重开后旧局挂起的 AI 回调不得在新棋盘落子。"""
    w = gomoku.create(Config())
    _gomoku_click(w, 7, 7)
    _gomoku_click(w, 8, 8)                    # AI 尚未回手：应被锁
    assert _stones(w.board, "X") == 1, "清言思考中不得让玩家连下两子"
    gen = w._gen
    w._pet(gen)                               # 定时器到点
    assert _stones(w.board, "O") == 1 and not w.locked
    _gomoku_click(w, 8, 8)
    stale = w._gen
    w._reset()
    w._pet(stale)                             # 上局挂起的回调
    assert _stones(w.board, "O") == 0, "旧局 AI 定时器不得在新局落子"
    assert not w.locked
    _gomoku_click(w, 7, 7)
    assert _stones(w.board, "X") == 1
    w.close()


def test_tictactoe_stale_timer_and_opp():
    """井字棋：重开后旧局 _pet_move 作废；me='X' 时对手是 'O'。"""
    w = tictactoe.create(Config())
    w._click(0)
    assert w.locked
    stale = w._gen
    w._reset()
    w._pet_move(stale)
    assert w.board == " " * 9, "旧局 AI 定时器不得在新局落子"
    assert not w.locked
    w._click(4)
    w._pet_move(w._gen)
    assert w.board.count("O") == 1 and not w.locked
    w.close()
    # 对手标记：me='X' 时应识别 O 的立即取胜点并堵住
    b = "OO XX    "
    pos, is_block = tictactoe.best_move("OO  X    ", "X")
    assert pos == 2 and is_block, (pos, is_block)
    pos, is_block = tictactoe.smart_move("OO  X    ", "X")
    assert pos == 2 and is_block
    assert tictactoe.smart_move(b, "X")[0] == 5      # 自己能赢优先


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("第五轮 R4 游戏修复测试通过 ✔")
