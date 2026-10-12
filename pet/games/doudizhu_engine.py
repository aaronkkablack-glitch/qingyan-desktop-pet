# -*- coding: utf-8 -*-
"""斗地主引擎：牌值编码 / 牌型识别与比较 / 合法出牌生成 / 规则 AI。

牌值：3..10=3..10, J=11, Q=12, K=13, A=14, 2=15, 小王=16, 大王=17。
牌型（斗地主完整规则）：单/对/三/三带一/三带二/炸弹/王炸/顺子(≥5)/连对(≥3)/
飞机(≥2连三)/飞机带单/飞机带对/四带二单/四带二对。
牌局：叫分制（0-3，最高者当地主拿 3 张底牌），地主先出，一手两家"不要"后重新自由出。
"""
import random
from collections import Counter
from dataclasses import dataclass, field

RANK_NAME = {11: "J", 12: "Q", 13: "K", 14: "A", 15: "2", 16: "小王", 17: "大王"}
DECK = [r for r in range(3, 16) for _ in range(4)] + [16, 17]


def rank_label(r: int) -> str:
    return RANK_NAME.get(r, str(r))


@dataclass
class Move:
    cards: list               # 牌值列表（显示排序）
    type: str = ""            # single/pair/triple/triple1/triple2/bomb/rocket/straight/
                              # pairseq/plane/plane1/plane2/four2/four22/pass
    rank: int = 0             # 比较大小的锚点（三带锚三子、顺子锚最小等）
    length: int = 0           # 顺子/连对/飞机的"连"数
    @classmethod
    def pass_move(cls):
        return cls(cards=[], type="pass")

    @property
    def is_pass(self) -> bool:
        return self.type == "pass"

    @property
    def is_bomb(self) -> bool:
        return self.type in ("bomb", "rocket")


def beats(a: Move, b: Move) -> bool:
    """a 能否压住 b（b 为自由出牌时任何合法牌型都能出）。"""
    if b.is_pass:
        return True
    if a.type == "rocket":
        return True
    if a.type == "bomb":
        return b.type != "rocket" and (b.type != "bomb" or a.rank > b.rank)
    if b.is_bomb:
        return False
    return (a.type == b.type and a.length == b.length and a.rank > b.rank)


def parse_move(cards: list, last: Move | None = None) -> Move:
    """识别一手牌的牌型；不合法返回 type=''。"""
    cs = sorted(cards)
    n = len(cs)
    if n == 0:
        return Move.pass_move()
    cnt = Counter(cs)
    if any(not isinstance(r, int) or r not in range(3, 18) or count > (1 if r >= 16 else 4)
           for r, count in cnt.items()):
        return Move(cs, "")
    counts = sorted(cnt.values(), reverse=True)
    uniq = sorted(cnt)

    def cont(seq):
        return all(seq[i + 1] - seq[i] == 1 for i in range(len(seq) - 1))

    if n == 1:
        return Move(cs, "single", cs[0])
    if n == 2:
        if cs == [16, 17]:
            return Move(cs, "rocket", 17)
        if cs[0] == cs[1]:
            return Move(cs, "pair", cs[0])
    if n == 3 and counts == [3]:
        return Move(cs, "triple", uniq[0])
    if n == 4:
        if counts == [4]:
            return Move(cs, "bomb", uniq[0])
        if counts == [3, 1]:
            return Move(cs, "triple1", [r for r in uniq if cnt[r] == 3][0])
    if n == 5 and counts == [3, 2]:
        return Move(cs, "triple2", [r for r in uniq if cnt[r] == 3][0])
    # 顺子（3..A，不含 2 和王）
    if n >= 5 and counts == [1] * n and cont(cs) and cs[-1] <= 14:
        return Move(cs, "straight", cs[0], n)
    # 连对
    if n >= 6 and n % 2 == 0 and len(uniq) * 2 == n and all(cnt[r] == 2 for r in uniq) \
            and cont(uniq) and uniq[-1] <= 14:
        return Move(cs, "pairseq", uniq[0], len(uniq))
    # 飞机（≥2 连三）不带 / 带单 / 带对
    tri = [r for r in uniq if cnt[r] >= 3 and r <= 14]
    planes = []
    for pl in _plane_runs(tri):
        k = len(pl)
        if k >= 2:
            base = k * 3
            rest_cnt = cnt.copy()
            for r in pl:
                rest_cnt[r] -= 3
                if rest_cnt[r] <= 0:
                    del rest_cnt[r]
            rest = [r for r, n in rest_cnt.items() for _ in range(n)]
            if n == base and len(uniq) == k:
                planes.append(Move(cs, "plane", pl[0], k))
            if n == base + k and not (16 in rest and 17 in rest) and not any(r in pl for r in rest):
                planes.append(Move(cs, "plane1", pl[0], k))
            if n == base + 2 * k and not any(r in pl for r in rest) \
                    and all(v == 2 for v in Counter(rest).values()):
                planes.append(Move(cs, "plane2", pl[0], k))
    if planes:
        matching = [m for m in planes if last and not last.is_pass and beats(m, last)]
        return (matching or planes)[0]
    # 四带二
    if n == 6 and counts == [4, 1, 1] or (n == 6 and counts == [4, 2]):
        four = [r for r in uniq if cnt[r] == 4]
        if four:
            return Move(cs, "four2", four[0])
    if n == 8 and counts == [4, 2, 2]:
        fours = [r for r in uniq if cnt[r] == 4]
        if len(fours) == 1:
            return Move(cs, "four22", fours[0])
    return Move(cs, "")


def _plane_runs(triples):
    """所有连续三子段（≥2 连）。"""
    out = []
    for i in range(len(triples)):
        run = [triples[i]]
        j = i
        while j + 1 < len(triples) and triples[j + 1] == run[-1] + 1:
            run.append(triples[j + 1])
            j += 1
        if len(run) >= 2:
            out.extend(run[:length] for length in range(2, len(run) + 1))
    return sorted(out, key=lambda run: (-len(run), run[0]))


# ---------------------------------------------------------------------------
# 合法出牌生成
# ---------------------------------------------------------------------------

def gen_moves(hand: list, last: Move) -> list[Move]:
    """生成能压住 last 的所有出牌（last 为 pass 时生成全部合理主动出牌，同型只保留代表）。"""
    cnt = Counter(hand)
    if last.is_pass:
        return _gen_all(cnt)
    return [m for m in _gen_all(cnt, like=last) if beats(m, last)]


def _gen_all(cnt: Counter, like: Move | None = None) -> list[Move]:
    out = []
    uniq = sorted(cnt)

    def ok(m):
        return like is None or (m.type == like.type and m.length == like.length)

    if like is None or like.type == "single":
        for r in uniq:
            out.append(Move([r], "single", r))
    if like is None or like.type == "pair":
        for r in uniq:
            if cnt[r] >= 2:
                out.append(Move([r] * 2, "pair", r))
    if like is None or like.type in ("triple", "triple1", "triple2"):
        for r in uniq:
            if cnt[r] >= 3:
                out.append(Move([r] * 3, "triple", r))
                for x in uniq:
                    if x != r:
                        out.append(Move(sorted([r] * 3 + [x]), "triple1", r))
                    if x != r and cnt[x] >= 2:
                        out.append(Move(sorted([r] * 3 + [x] * 2), "triple2", r))
    if like is None or like.type == "straight":
        run = [r for r in uniq if r <= 14]
        for i in range(len(run)):
            for end in range(i + 4, len(run)):
                seg = run[i:end + 1]
                if seg[-1] - seg[0] == len(seg) - 1:
                    out.append(Move(seg, "straight", seg[0], len(seg)))
    if like is None or like.type == "pairseq":
        pr = [r for r in uniq if r <= 14 and cnt[r] >= 2]
        for i in range(len(pr)):
            for end in range(i + 2, len(pr)):
                seg = pr[i:end + 1]
                if seg[-1] - seg[0] == len(seg) - 1:
                    out.append(Move([x for r in seg for x in (r, r)], "pairseq", seg[0], len(seg)))
    if like is None or like.type in ("plane", "plane1", "plane2"):
        tri = [r for r in uniq if cnt[r] >= 3 and r <= 14]
        for pl in _plane_runs(tri):
            k = len(pl)
            out.append(Move([x for r in pl for x in (r,) * 3], "plane", pl[0], k))
            rest_cnt = cnt.copy()
            for r in pl:
                rest_cnt[r] -= 3
                if rest_cnt[r] <= 0:
                    del rest_cnt[r]
            rest = [r for r, n in rest_cnt.items() for _ in range(n)]
            # 带单：从剩余牌里选 k 张（同型对齐时枚举小组合即可，取全部组合）
            for combo in _choose(rest, k):
                out.append(Move(sorted([x for r in pl for x in (r,) * 3] + list(combo)),
                                "plane1", pl[0], k))
            rest_pairs = [r for r, n in rest_cnt.items() if n >= 2]
            for combo in _choose_pairs(rest_pairs, k):
                out.append(Move(sorted([x for r in pl for x in (r,) * 3] + list(combo)),
                                "plane2", pl[0], k))
    if like is None or like.type == "four2":
        for r in uniq:
            if cnt[r] == 4:
                rest = [x for x in uniq if x != r]
                for a in range(len(rest)):
                    for b in range(a + 1, len(rest)):
                        out.append(Move(sorted([r] * 4 + [rest[a], rest[b]]), "four2", r))
    if like is None or like.type == "four22":
        for r in uniq:
            if cnt[r] == 4:
                pr = [x for x in uniq if x != r and cnt[x] >= 2]
                for a in range(len(pr)):
                    for b in range(a + 1, len(pr)):
                        out.append(Move(sorted([r] * 4 + [pr[a]] * 2 + [pr[b]] * 2), "four22", r))
    # 炸弹/王炸可压任意牌型：跟牌时也总是生成，由 beats() 过滤（此前只在同型时生成，AI/提示永远不炸、王炸压不了炸）
    for r in uniq:
        if cnt[r] == 4:
            out.append(Move([r] * 4, "bomb", r))
    if 16 in cnt and 17 in cnt:
        out.append(Move([16, 17], "rocket", 17))
    # 去重（同 type/rank/length 只留一个代表，带牌选最省的）
    seen = {}
    for m in out:
        parsed = parse_move(m.cards, like)
        if (parsed.type, parsed.rank, parsed.length) != (m.type, m.rank, m.length):
            continue
        key = (m.type, m.rank, m.length)
        if key not in seen or len(m.cards) < len(seen[key].cards):
            seen[key] = m
    return sorted(seen.values(), key=lambda m: (m.rank, m.length))


def _choose(items: list, k: int, limit=40):
    """从 items（可重复值代表不同张）选 k 张的组合，量截断防爆。"""
    from itertools import combinations
    return list(combinations(items, k))[:limit]


def _choose_pairs(uniq_have_cnt, k, limit=20):
    from itertools import combinations
    prs = [x for x in uniq_have_cnt]
    return [tuple(x for r in c for x in (r, r)) for c in combinations(prs, k)][:limit]


# ---------------------------------------------------------------------------
# 规则 AI
# ---------------------------------------------------------------------------

@dataclass
class AIState:
    hand: list = field(default_factory=list)
    """简单规则 AI：叫分评估 + 拆牌出牌 + 基础配合。"""


def eval_bid(hand: list) -> int:
    """叫分：手牌强度评分 → 0-3。"""
    cnt = Counter(hand)
    s = 0
    s += 8 if 17 in cnt else 0
    s += 6 if 16 in cnt else 0
    s += 3 * cnt.get(15, 0)          # 2
    s += sum(5 for r, n in cnt.items() if n == 4)      # 炸弹
    s += 2 if cnt.get(16) and cnt.get(17) else 0
    s += cnt.get(14, 0)              # A
    if s >= 22:
        return 3
    if s >= 16:
        return 2
    if s >= 11:
        return 1
    return 0


def ai_bid(hand: list, current_high: int) -> int:
    want = eval_bid(hand)
    return want if want > current_high else 0


def _decompose(hand: list) -> dict:
    """粗拆手牌：炸弹/火箭保留，三子、对、单归类（顺子暂不拆——出牌时单张拼顺子由生成器承担）。"""
    cnt = Counter(hand)
    groups = {"bomb": [], "triple": [], "pair": [], "single": []}
    for r in sorted(cnt):
        n = cnt[r]
        if r in (16, 17):
            groups["single"].extend([r] * n)
        elif n == 4:
            groups["bomb"].append(r)
        elif n == 3:
            groups["triple"].append(r)
        elif n == 2:
            groups["pair"].append(r)
        else:
            groups["single"].append(r)
    return groups


def ai_lead(hand: list) -> Move:
    """自由出牌：优先出长顺/组合，其次最小单/对；收尾直接走；不轻易拆炸。"""
    moves = gen_moves(hand, Move.pass_move())
    non_bomb = [m for m in moves if not m.is_bomb]
    pool = non_bomb or moves
    # 剩最后一组合：直接出
    if len(pool) == 1:
        return pool[0]
    # 手牌 ≤5 时偏激进：出最大的组合收尾
    if len(hand) <= 4:
        return max(pool, key=lambda m: (m.rank, len(m.cards)))
    # 常规：出"最小"的非炸组合（单/对/顺子都参与，rank 低优先，长顺优先消耗）
    def cost(m):
        big = sum(1 for c in m.cards if c >= 15)
        return (m.rank, big, -len(m.cards))
    return min(pool, key=cost)


def ai_follow(hand: list, last: Move, last_owner_is_teammate: bool,
              teammate_cards_left: int, enemy_min_cards: int) -> Move:
    """跟牌：能压取最小代价；队友大牌不压；队友快走了不压；炸弹看时机。"""
    moves = gen_moves(hand, last)
    if not moves:
        return Move.pass_move()
    normal = [m for m in moves if not m.is_bomb]
    bombs = [m for m in moves if m.is_bomb]
    if teammate_cards_left <= 4 and last_owner_is_teammate:
        return Move.pass_move()                 # 队友快赢，让他走
    if last_owner_is_teammate and last.rank >= 13:
        return Move.pass_move()                 # 队友的大牌不压
    if normal:
        def cost(m):
            big = sum(1 for c in m.cards if c >= 15)
            return (m.rank, big, len(m.cards))
        best = min(normal, key=cost)
        # 敌人只剩 1-2 张时别送小牌：小单/小对改 pass 留大牌
        if enemy_min_cards <= 2 and last.type == "single" and best.rank < 11 and any(
                m.rank >= 13 for m in normal):
            best = min((m for m in normal if m.rank >= 13), key=lambda m: m.rank)
        return best
    if bombs and (enemy_min_cards <= 8 or last.rank >= 13):
        return min(bombs, key=lambda m: m.rank)
    return Move.pass_move()
