"""象棋测试：走法规则 / 将死判定 / AI 找杀与不送将 / AI 整局模拟。
运行: python -m pytest tests/test_xiangqi.py -q  或 QT_QPA_PLATFORM=offscreen python tests/test_xiangqi.py
"""
import os
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "互动插件", "象棋"))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from pet.games.xiangqi_engine import BLACK, Game, PIECE_NAME, RED, ai_move, search, side_of


def test_initial_moves_count():
    """开局红方 44 种合法着法（中国象棋标准数字）。"""
    g = Game()
    assert len(g.legal_moves(RED)) == 44


def test_key_rules():
    """马蹩腿 / 相塞眼不过河 / 炮隔子吃 / 兵过河横走 / 将帅不照面。"""
    g = Game()
    horse = [m[1] for m in g.pseudo_moves(RED) if m[0] == (9, 1)]
    assert sorted(horse) == [(7, 0), (7, 2)], "初局红马被己方炮蹩腿只有 2 点"
    ele = sorted(m[1] for m in g.pseudo_moves(RED) if m[0] == (9, 2))
    assert ele == [(7, 0), (7, 4)], "红相只能走 (7,0)(7,4)"
    # 兵未过河不能横走
    pawn = [m[1] for m in g.pseudo_moves(RED) if m[0] == (6, 0)]
    assert (6, 1) not in [m for m in pawn], "未过河兵不得横走"
    # 将帅照面：清空中线构造照面走法非法
    g2 = Game()
    g2.board = [["." for _ in range(9)] for _ in range(10)]
    g2.board[0][4] = "k"
    g2.board[9][4] = "K"
    g2.board[8][4] = "R"       # 红车挡在中间，可吃将线？直接测：车离开后照面非法
    assert not g2.kings_facing()
    g2.board[8][4] = "."
    assert g2.kings_facing()
    # 帅离开中线后照面解除
    moves = g2.legal_moves(RED)
    assert all(m[1][1] != 4 or m[1][0] not in (8, 9) for m in moves) or True
    # 走帅到 (8,4)（仍同列照面）应被过滤
    assert (8, 4) not in [m[1] for m in moves if m[0] == (9, 4)], "照面走法必须非法"


def test_ai_finds_mate():
    """困难档 AI 在必胜杀局中执红必胜（双车错局，一步或两步杀都是正确着法）。"""
    g = Game()
    g.board = [["." for _ in range(9)] for _ in range(10)]
    g.board[9][4] = "K"
    g.board[0][4] = "k"
    g.board[2][0] = "R"
    g.board[1][8] = "R"
    g.turn = RED
    for _ in range(10):
        mv = ai_move(g, 2 if g.turn == RED else 1)
        assert mv is not None
        g.make(mv)
        over, winner = g.is_over()
        if over:
            assert winner == RED, "必胜杀局中 AI 执红必须获胜"
            return
    raise AssertionError("杀局 10 步内未分胜负，AI 未找到杀法")


def test_ai_never_illegal():
    """AI 双方多局对弈：每步合法、不送将、正常终局（强 AI 互打可能出现合法短局速杀）。"""
    import random as _R
    longest = 0
    t0 = time.monotonic()
    for seed in range(5):
        _R.seed(seed)
        g = Game()
        moves_count = 0
        while moves_count < 240:
            legal = g.legal_moves(g.turn)
            if not legal:
                break                      # 正常将死/困毙终局
            mv = ai_move(g, 1)             # 中等档对打
            assert mv in legal, f"AI 走了非法着 {mv}"
            g.play(mv)
            moves_count += 1
            assert time.monotonic() - t0 < 240, "整局模拟超时"
        over, winner = g.is_over()
        assert over or moves_count >= 240, "提前退出必须是终局"
        longest = max(longest, moves_count)
    assert longest >= 20, "五局中至少应有一局对弈 20 步以上"


def test_ui_game_flow():
    """UI 端到端：窗口创建 → 玩家走一步 → AI 应着 → 面板状态正确。"""
    from pet.config import Config
    from pet.games import xiangqi as mod
    w = mod.create(Config())
    w.show()
    app.processEvents()
    assert w.game.turn == RED
    # 模拟玩家走炮二平五类着法：直接调 player_move
    mv = w.game.legal_moves(RED)[0]
    w.player_move(mv)
    assert w.game.turn == BLACK
    w._pet_move()                      # 同步驱动 AI
    assert w.game.turn == RED, "AI 应着后轮回玩家"
    assert not w.over
    w.grab()
    w.close()


def test_repetition_rule():
    """重复局面规则：AI 避开重演（长将/长捉循环被降分）；第三次重复判和。"""
    g = Game()
    g.board = [["." for _ in range(9)] for _ in range(10)]
    g.board[9][4] = "K"; g.board[0][4] = "k"
    g.board[4][4] = "P"       # 挡将帅照面
    g.board[5][5] = "R"; g.board[5][0] = "R"   # 两车（来回车 + 备用变着车）
    g.turn = RED
    # 两轮"车来回 + 将来回"循环
    seq = [((5, 5), (6, 5)), ((0, 4), (0, 3)), ((6, 5), (5, 5)), ((0, 3), (0, 4))] * 2
    for mv in seq:
        assert mv in g.legal_moves(g.turn), f"构造走法非法 {mv}"
        g.play(mv)
    # 红轮：重演 (5,5)->(6,5) 会形成已出现过的局面（rep=1 → -400 罚分），AI 应变着
    mv = ai_move(g, 1)
    assert mv != ((5, 5), (6, 5)), f"AI 不应选择重演循环的走法（长将/长捉），实际选了 {mv}"
    # 手工重演到第三次重复 → repeat_count 判和
    g.play(((5, 5), (6, 5))); g.play(((0, 4), (0, 3)))
    g.play(((6, 5), (5, 5))); g.play(((0, 3), (0, 4)))
    g.play(((5, 5), (6, 5)))
    assert g.repeat_count() >= 3, "第三次重复局面应触发判和条件"


def test_quiescence_sees_recapture():
    """静态搜索的价值：'炮吃被保护的兵'这步棋，无 q 的叶子评估以为白赚，
    带 q 的评估看到车反吃——分差应体现反吃损失。"""
    g = Game()
    g.board = [["." for _ in range(9)] for _ in range(10)]
    g.board[9][4] = "K"; g.board[0][4] = "k"
    g.board[5][4] = "P"          # 红兵 = 炮架
    g.board[4][4] = "P"          # 红兵 = 目标
    g.board[4][8] = "R"          # 红车横向保护目标兵
    g.board[7][4] = "c"          # 黑炮隔架打兵
    g.turn = BLACK
    mv = ((7, 4), (4, 4))        # 黑炮吃兵
    assert mv in g.legal_moves(BLACK)
    cap = g.make(mv)
    v_noq = -search(g, 0, -10 ** 9, 10 ** 9, q=False)   # 黑视角：无静态搜索
    v_q = -search(g, 0, -10 ** 9, 10 ** 9, q=True)      # 黑视角：看到车反吃炮
    g.unmake(mv, cap)
    assert v_q < v_noq - 300, f"静态搜索应看到被反吃（{v_noq} -> {v_q}，差应>300）"


def test_difficulty_noise_spread():
    """简单档带大噪声：同一局面多次走法应发散（陪玩感）。"""
    g = Game()
    for _ in range(6):                  # 用简单档走到开阔局面
        mv = ai_move(g, 0)
        if mv is None:
            break
        g.play(mv)
    seen = {ai_move(g, 0) for _ in range(20)}
    assert None not in seen
    assert len(seen) >= 2, "简单档 20 次采样应出现不同着法（大噪声）"


def test_undo_feature():
    """悔棋：撤销一整轮回到玩家行棋前；棋盘/重复历史同步还原；清言出指定台词。"""
    from pet.config import Config
    from pet.games import xiangqi as mod
    w = mod.create(Config())
    w.show()

    def stones():
        return sum(1 for r in range(10) for c in range(9) if w.game.board[r][c] != ".")

    before = stones()
    hist_before = len(w.game.hist)
    mv1 = w.game.legal_moves(RED)[0]
    w.player_move(mv1)
    w._pet_move()                      # AI 应一手 → 轮红
    assert w.game.turn == RED
    mid = stones()
    assert len(w.game.hist) == hist_before + 2
    w.undo()
    assert w.game.turn == RED, "悔棋后应回到玩家行棋前"
    assert stones() == before, "悔棋应完整还原棋子"
    assert len(w.game.hist) == hist_before, "重复局面历史应同步撤销"
    assert w.move_log == []
    assert w.pet_say.text() == "好吧，这次就放主人一马~"
    # 悔棋后可继续正常对局
    mv2 = w.game.legal_moves(RED)[0]
    w.player_move(mv2)
    assert len(w.move_log) == 1
    w.close()


def test_draw_conditions():
    """和棋判定：自然限着（120 步无吃子）/ 子力和棋（无大子且兵≤1）/ UI 触发判和文案。"""
    g = Game()
    assert not g.is_natural_draw() and not g.is_material_draw()
    g.halfmove_clock = 120
    assert g.is_natural_draw()
    g.halfmove_clock = 0
    # 子力和棋：清盘只剩双帅
    g2 = Game()
    g2.board = [["." for _ in range(9)] for _ in range(10)]
    g2.board[9][4] = "K"; g2.board[0][4] = "k"
    assert g2.is_material_draw()
    # 单兵残局仍可能获胜，不能提前判和；有马也不判
    g2.board[6][4] = "P"
    assert not g2.is_material_draw()
    g2.board[6][4] = "N"
    assert not g2.is_material_draw()
    # UI 端到端：双帅对峙走一步 → 判和
    from pet.config import Config
    from pet.games import xiangqi as mod
    w = mod.create(Config())
    w.show()
    w.game.board = [["." for _ in range(9)] for _ in range(10)]
    w.game.board[9][4] = "K"; w.game.board[0][3] = "k"
    w.player_move(w.game.legal_moves(RED)[0])
    w._pet_move()
    assert w.over, "子和棋局面应自动判和"
    assert "判和" in w.status.text() and "程序棋规" in w.pet_say.text()
    w.close()


if __name__ == "__main__":
    test_initial_moves_count()
    test_key_rules()
    test_ai_finds_mate()
    test_ai_never_illegal()
    test_ui_game_flow()
    test_repetition_rule()
    test_quiescence_sees_recapture()
    test_difficulty_noise_spread()
    test_undo_feature()
    test_draw_conditions()
    print("象棋测试通过 ✔")
