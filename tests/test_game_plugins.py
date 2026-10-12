"""互动游戏测试：内置+插件合并发现 / 坏插件跳过 / 井字棋 AI 不败与分级 / 五子棋规则与防守。
运行: python -m pytest tests/test_game_plugins.py -q  或 QT_QPA_PLATFORM=offscreen python tests/test_game_plugins.py
"""
import os
import shutil
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from pet import game_plugins
from pet.config import Config
from pet.games import gomoku, tictactoe


def _load_plugin(name):
    """加载游戏模块：内置两游戏在 pet.games，按名取。"""
    return {"井字棋": tictactoe, "五子棋": gomoku}[name]


def test_all_games_builtin_first():
    """菜单合并列表：内置固定四游戏（象棋在斗地主上面），外部插件（若有）在后。"""
    games = game_plugins.all_games()
    titles = [g.title for g in games]
    assert titles[:4] == ["井字棋", "五子棋", "象棋", "斗地主"], titles
    assert all(g.name.startswith("builtin:") for g in games[:4])
    for g in games:
        assert callable(g.module.create)


def test_discover_no_external():
    """插件目录清空后（斗地主/象棋已内置）discover 为空，内置不受影响。"""
    assert game_plugins.discover() == []


def test_discover_skips_broken_plugin():
    """坏插件（缺 TITLE/create / 语法错）只跳过自己，不炸整表；好插件能被外部发现。"""
    tmp = tempfile.mkdtemp()
    old = game_plugins.plugin_root
    try:
        os.makedirs(os.path.join(tmp, "坏的"), exist_ok=True)
        with open(os.path.join(tmp, "坏的", "plugin.py"), "w", encoding="utf-8") as f:
            f.write("TITLE = None\n")   # 协议不符
        os.makedirs(os.path.join(tmp, "崩的"), exist_ok=True)
        with open(os.path.join(tmp, "崩的", "plugin.py"), "w", encoding="utf-8") as f:
            f.write("this is not python(((\n")
        os.makedirs(os.path.join(tmp, "好的"), exist_ok=True)
        with open(os.path.join(tmp, "好的", "plugin.py"), "w", encoding="utf-8") as f:
            f.write("TITLE = '好的'\n\n\ndef create(cfg, parent=None):\n    return None\n")
        game_plugins.plugin_root = lambda: tmp
        found = [p.name for p in game_plugins.discover()]
        assert found == ["好的"], f"坏插件应被跳过，实际 {found}"
        allg = [g.title for g in game_plugins.all_games()]
        assert allg[:2] == ["井字棋", "五子棋"] and "好的" in allg, allg
    finally:
        game_plugins.plugin_root = old
        shutil.rmtree(tmp, ignore_errors=True)


def test_tictactoe_ai_unbeatable():
    """井字棋 minimax：玩家任意开局着法，清言回手后玩家都无法立即取胜。"""
    ttt = _load_plugin("井字棋")
    X = "X"
    # 玩家第一步走每个位置，AI 回应后，检查玩家不存在一步致胜点
    for first in range(9):
        b = " " * 9
        b = b[:first] + X + b[first + 1:]
        pos, _ = ttt.best_move(b, "O")
        assert 0 <= pos < 9
        b = b[:pos] + "O" + b[pos + 1:]
        if ttt.winner(b):
            continue
        for second in range(9):
            if b[second] != " ":
                continue
            b2 = b[:second] + X + b[second + 1:]
            assert ttt.winner(b2) != "X", f"玩家先手{first}后存在必胜点{second}"
    # 阻挡检测：玩家双活二 imminent，AI 必须占 1
    b = "X X O    "  # 0,2 位 X，AI 必须占 1
    pos, is_block = ttt.best_move(b, "O")
    assert pos == 1 and is_block


def test_tictactoe_levels():
    """中等=赢/堵优先；简单=自己能赢也会赢但其余随机。"""
    ttt = _load_plugin("井字棋")
    # 中等：自己能赢就赢（O 在 0,1，下 2 即胜）
    b = "OO XX    "
    pos, _ = ttt.smart_move(b, "O")
    assert pos == 2
    # 中等：不能赢时必堵（X 在 4,5 位，行(3,4,5)缺口是 3）
    b = "O   XX   "
    pos, is_block = ttt.smart_move(b, "O")
    assert pos == 3 and is_block
    # 简单：自己也顺手赢
    b = "OO X     "
    pos, _ = ttt.lazy_move(b, "O")
    assert pos == 2
    # 简单：无胜机时返回合法空格
    b = "XO  X   O"
    pos, _ = ttt.lazy_move(b, "O")
    assert 0 <= pos < 9 and b[pos] == " "


def test_gomoku_rules_and_defense():
    """五子棋：五连判定四方向；各难度 AI 会堵玩家的活三；困难级必胜/必堵。"""
    g = _load_plugin("五子棋")
    bd = [[" "] * g.N for _ in range(g.N)]
    for i in range(4):
        bd[7][3 + i] = "X"
    bd[7][3 + 4] = " "  # X _ X X X X 布局：3,4,5,6 连四，7 空
    # 玩家下 (7,7) 成五连
    bd[7][7] = "X"
    assert g.check_win(bd, 7, 7)
    # 困难难度（确定性最强棋力）：玩家横向活三 → 必堵两端延长点
    # （中等档是 top3 随机挑、下法灵活，不做必堵断言）
    bd = [[" "] * g.N for _ in range(g.N)]
    bd[7][6] = bd[7][7] = bd[7][8] = "X"     # 活三
    x, y = g.ai_move(bd, 2)
    assert (y, x) == (7, 5) or (y, x) == (7, 9), f"困难应堵活三两端，实际 {(x, y)}"
    # 困难：自己有五连点时必下（O 在 5-8，(4,7)/(9,7) 均可成五连）
    bd = [[" "] * g.N for _ in range(g.N)]
    for i in (5, 6, 7, 8):
        bd[7][i] = "O"
    assert g.ai_move(bd, 2) in ((4, 7), (9, 7)), "困难级必须抓住五连制胜点"
    # 困难：对方冲四活点必堵
    bd = [[" "] * g.N for _ in range(g.N)]
    for i in (5, 6, 7, 8):
        bd[7][i] = "X"
    x, y = g.ai_move(bd, 2)
    assert (x, y) in ((4, 7), (9, 7)), f"困难级必须堵对方五连点，实际 {(x, y)}"


def test_plugin_create_returns_window():
    """工厂返回可显示窗口（协议端到端）。"""
    for name, title in (("井字棋", "井字棋"), ("五子棋", "五子棋")):
        mod = _load_plugin(name)
        win = mod.create(Config())
        win.show()
        app.processEvents()
        assert win.isVisible()
        win.close()


def test_switch_level_midgame():
    """对局中途切换难度：清言下一手立即按新棋力走（难度是落子时实时读取的）。"""
    ttt = _load_plugin("井字棋")
    w = ttt.create(Config())
    # 玩家 X 已占 0,1（顶行只差 2），清言 O 在 3,6（无制胜点）——先切到中等再让她落子
    w.board = "XX O  O  "
    w._set_level(1)
    w.locked = True
    w._pet_move()
    assert w.board[2] == "O", "切到中等后，清言下一手必须堵住玩家的制胜点"

    g = _load_plugin("五子棋")
    gw = g.create(Config())
    for i in (6, 7, 8):
        gw.board[7][i] = "X"          # 玩家横向活三
    gw._set_level(2)                  # 中途切困难
    gw._pet()
    assert gw.board[7][5] == "O" or gw.board[7][9] == "O", "切到困难后，清言必须堵活三"


def test_pet_hooks_integration():
    """互动游戏联动桌宠动作：开局思考 / 清言胜=win / 清言负=lose / 关窗=idle。"""
    from pet.config import Config
    from PySide6.QtCore import QObject, Signal

    class _GlmStub(QObject):
        pass

    got = []
    hooks = got.append

    # 井字棋：清言(O)三连 → win；关窗 → idle
    ttt = tictactoe.create(Config())
    ttt.pet_hooks = hooks
    for i, ch in [(0, "X"), (3, "O"), (1, "X"), (4, "O"), (8, "X"), (5, "O")]:
        ttt._put(i, ch)          # O 连成中线 3-4-5
    ttt._check()
    assert "win" in got, got
    ttt.close()
    assert got[-1] == "idle"

    # 五子棋：玩家(X)五连 → lose
    gm = gomoku.create(Config())
    gm.pet_hooks = hooks
    got.clear()
    for i in range(5):
        gm.board[7][4 + i] = "X"
    gm._end(8, 7, gomoku.PET_LOSE)
    assert "lose" in got, got

    # 象棋（内置）：清言(黑)胜 → win
    from pet.games import xiangqi as xq_mod
    xq = xq_mod.create(Config())
    xq.pet_hooks = hooks
    got.clear()
    xq._finish(1)               # winner=BLACK → 清言胜
    assert "win" in got, got
    xq.close()
    assert got[-1] == "idle"
    # 未注入钩子的窗口不得报错（老插件兼容）
    ttt2 = tictactoe.create(Config())
    ttt2._pet_state("win")
    ttt2.close()


if __name__ == "__main__":
    test_all_games_builtin_first()
    test_discover_no_external()
    test_discover_skips_broken_plugin()
    test_tictactoe_ai_unbeatable()
    test_tictactoe_levels()
    test_gomoku_rules_and_defense()
    test_switch_level_midgame()
    test_plugin_create_returns_window()
    test_pet_hooks_integration()
    print("互动游戏测试通过 ✔")
