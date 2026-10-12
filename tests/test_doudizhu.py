"""斗地主测试：牌型识别 / 比较 / 出牌生成 / AI 行为 / 整局模拟（防死局）。
运行: python -m pytest tests/test_doudizhu.py -q  或 QT_QPA_PLATFORM=offscreen python tests/test_doudizhu.py
"""
import os
import random
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "互动插件", "斗地主"))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from pet.games.doudizhu_engine import (DECK, Move, ai_bid, ai_follow, ai_lead, beats, gen_moves,
                    parse_move)


def test_parse_all_types():
    assert parse_move([3]).type == "single"
    assert parse_move([3, 3]).type == "pair"
    assert parse_move([3, 3, 3]).type == "triple"
    assert parse_move([3, 3, 3, 5]).type == "triple1"
    assert parse_move([3, 3, 3, 5, 5]).type == "triple2"
    assert parse_move([3, 4, 5, 6, 7]).type == "straight"
    assert parse_move([10, 11, 12, 13, 14]).type == "straight"
    assert parse_move([11, 12, 13, 14, 15]).type == ""        # 顺子不能含 2
    assert parse_move([3, 3, 4, 4, 5, 5]).type == "pairseq"
    assert parse_move([10, 10, 10, 11, 11, 11]).type == "plane"
    assert parse_move([10, 10, 10, 11, 11, 11, 3, 4]).type == "plane1"
    assert parse_move([10, 10, 10, 11, 11, 11, 3, 3, 4, 4]).type == "plane2"
    assert parse_move([8, 8, 8, 8]).type == "bomb"
    assert parse_move([16, 17]).type == "rocket"
    assert parse_move([9, 9, 9, 9, 3, 4]).type == "four2"
    assert parse_move([9, 9, 9, 9, 3, 3, 4, 4]).type == "four22"
    assert parse_move([3, 4, 6]).type == ""                    # 不成牌型
    assert parse_move([3, 4, 5, 6]).type == ""                 # 顺子至少 5 张


def test_beats_rules():
    assert beats(parse_move([13]), parse_move([12]))
    assert not beats(parse_move([12]), parse_move([13]))
    assert beats(parse_move([8, 8, 8, 8]), parse_move([14]))            # 炸压单
    assert beats(parse_move([16, 17]), parse_move([8, 8, 8, 8]))        # 王炸压炸
    assert not beats(parse_move([8, 8, 8, 8]), parse_move([16, 17]))
    assert not beats(parse_move([4, 5, 6, 7, 8]), parse_move([3, 4, 5, 6, 7, 8]))  # 长度不同
    assert beats(parse_move([10, 10, 10, 5]), parse_move([9, 9, 9, 5]))  # 三带一比三子
    assert not beats(parse_move([9, 9, 9, 5]), parse_move([9, 9, 9, 6]))  # 三子同级压不住


def test_gen_moves_follow():
    hand = [3, 3, 3, 4, 5, 6, 10, 10, 13, 13, 13, 8, 8, 8, 8]
    mv = parse_move([12])                     # 压 Q 单
    moves = gen_moves(hand, mv)
    # 第五轮修正：跟牌时炸弹也必须生成（此前跟单张永远不出炸，是 bug）
    assert all((m.type == "single" and m.rank > 12) or m.is_bomb for m in moves)
    assert any(m.rank == 13 for m in moves)
    assert any(m.is_bomb for m in moves), "手里有 8888，跟单张时炸弹应在候选里"
    # 炸弹也能生成（压单时非炸优先由 AI 选，生成器应同时给炸）
    mv2 = parse_move([14, 14])                # 压 AA 对
    moves2 = gen_moves(hand, mv2)
    assert moves2 == [] or all(m.is_bomb or (m.type == "pair" and m.rank > 14) for m in moves2)


def test_ai_bid_and_lead():
    strong = [17, 16, 15, 15, 14, 14, 13, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4]
    weak = [3, 3, 4, 4, 5, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
    assert ai_bid(strong, 0) >= 2
    assert ai_bid(weak, 0) <= 1
    lead = ai_lead(weak)
    assert parse_move(lead.cards).type != ""        # 主动出牌必须合法
    assert not lead.is_bomb                          # 不轻易甩炸


def test_ai_teammate_cooperation():
    """队友的大牌不压；队友快赢时不压。"""
    hand = [4, 4, 6, 7, 13, 13, 8, 8, 8]
    last = parse_move([14])                  # 队友出的 A
    mv = ai_follow(hand, last, True, 15, 17)
    assert mv.is_pass, "队友的 A 不应去压"
    last2 = parse_move([5])
    mv2 = ai_follow(hand, last2, True, 2, 17)    # 队友只剩 2 张
    assert mv2.is_pass, "队友快赢时应让他走"
    mv3 = ai_follow(hand, last2, False, 15, 17)  # 敌人出的 5——正常压
    assert not mv3.is_pass and mv3.rank > 5


def test_full_game_simulation():
    """三个规则 AI 打完整局×200：必须正常分出胜负（防死局/防非法出牌）。"""
    for seed in range(200):
        rng = random.Random(seed)
        deck = DECK[:]
        rng.shuffle(deck)
        hands = [sorted(deck[i * 17:(i + 1) * 17]) for i in range(3)]
        landlord = seed % 3
        hands[landlord] = sorted(hands[landlord] + deck[51:])
        turn = landlord
        last = Move.pass_move()
        last_owner = -1
        passes = 0
        for step in range(600):
            hand = hands[turn]
            if last.is_pass or last_owner == turn:
                mv = ai_lead(hand)
            else:
                same_camp = (turn == landlord) == (last_owner == landlord)
                teammate = same_camp and turn != landlord
                enemy_min = min(len(h) for i, h in enumerate(hands)
                                if i != turn and (i == landlord) != (turn == landlord))
                mv = ai_follow(hand, last, teammate, len(hands[last_owner]), enemy_min)
            if not mv.is_pass:
                parsed = parse_move(mv.cards)
                assert parsed.type, f"seed{seed} AI 出了非法牌 {mv.cards}"
                assert beats(parsed, last) or last.is_pass, \
                    f"seed{seed} AI 出牌压不住上家 {mv.cards} vs {last.cards}"
                for c in mv.cards:
                    hand.remove(c)
                last, last_owner, passes = parsed, turn, 0
            else:
                assert not last.is_pass, "自由出牌时 AI 不得 pass"
                passes += 1
            if not hand:
                break
            if passes >= 2:
                last = Move.pass_move()
                passes = 0
                turn = last_owner
                continue
            turn = (turn + 1) % 3
        else:
            raise AssertionError(f"seed{seed} 对局超过 600 步未结束（疑似死局）")
        # 走到这 = 有人出完，胜负正常产生
    assert True


def test_ui_bid_flow_no_crash():
    """回归（用户实测卡死根因）：AI 叫出真分时台词构造不得炸（list.format bug）；
    全不叫→重发→新一轮 AI 叫分整链路正常推进。"""
    from pet.config import Config
    from pet.games import doudizhu as mod
    w = mod.create(Config())
    w.show()

    # 直接驱动：AI 叫 3 分（此前该行 list.format 必炸）
    w.phase = "bid"
    w._apply_bid(1, 3)
    assert w.bid_high == 3 and w.bid_winner == 1
    # 叫 3 封顶 → 立即 _start_play，msg 已被地主宣言覆盖
    assert w.phase == "play" and w.seats[1].is_landlord

    # 全不叫 → 重发 → 新一轮 AI 起叫（同步驱动，覆盖用户卡死场景）
    from pet.games import doudizhu_engine as eng
    old_eval = eng.eval_bid
    eng.eval_bid = lambda hand: 0          # AI 全部评估不叫
    try:
        w.new_game()
        w.turn = w.bid_starter = 0
        w.bid_count = 0
        w._on_bid(0)                        # 玩家不叫
        guard = 0
        while w.phase == "bid" and guard < 20:
            if w.turn != 0:
                w._ai_bid()
            else:
                w._on_bid(0)
            guard += 1
        # 全不叫应触发重发（new_game 被 QTimer 调度；手动执行一次）
        w.new_game()
        assert w.phase == "bid" and w.bid_count == 0
        # 新一轮强制 AI 起叫（new_game 的 turn 随机，避免测试随机性）
        w.turn = w.bid_starter = random.choice([1, 2])
        # 恢复真实评估，AI 起叫（之前炸点）
        eng.eval_bid = old_eval
        w._ai_bid()
        assert w.bid_count >= 1, "重发后 AI 叫分必须推进"
    finally:
        eng.eval_bid = old_eval
    w.close()


def test_ui_play_selected_cleared():
    """回归（用户报"出牌点不动"）：出牌后选中必须清空；空选择不得提交。"""
    from pet.config import Config
    from pet.games import doudizhu as mod
    w = mod.create(Config())
    w.show()
    w._apply_bid(0, 3)                       # 玩家当地主，进入出牌
    assert w.phase == "play" and w.turn == 0
    hand = w.seats[0].hand
    # 空选择点出牌：不得提交（turn 不变、手牌不变）
    n0 = len(hand)
    w._on_btn("play")
    assert w.turn == 0 and len(w.seats[0].hand) == n0
    # 选中第一张出单
    w.selected = {0}
    w._on_btn("play")
    assert len(w.seats[0].hand) == n0 - 1, "出牌必须移除手牌"
    assert not w.selected, "出牌后选中必须清空（否则残留下标指向错牌）"
    w.close()


def test_new_game_clears_old_result():
    """回归（用户报"没出完牌却显示输了"）：再来一局必须擦掉上一局结算面板。"""
    from pet.config import Config
    from pet.games import doudizhu as mod
    w = mod.create(Config())
    w.show()
    w._apply_bid(0, 3)
    w.table.result = {"text": "😅 你输了", "detail": "残留面板"}   # 模拟上一局结算
    w.new_game()
    assert w.table.result is None, "新局必须清掉上一局的结算面板"
    assert w.phase == "bid"
    w.close()


if __name__ == "__main__":
    test_parse_all_types()
    test_beats_rules()
    test_gen_moves_follow()
    test_ai_bid_and_lead()
    test_ai_teammate_cooperation()
    test_full_game_simulation()
    test_ui_bid_flow_no_crash()
    test_ui_play_selected_cleared()
    test_new_game_clears_old_result()
    print("斗地主测试通过 ✔")
