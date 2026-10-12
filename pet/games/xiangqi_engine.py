# -*- coding: utf-8 -*-
"""中国象棋引擎：棋盘表示 / 走法生成 / 将军与将死判定 / alpha-beta AI。

棋盘：10 行 × 9 列，行 0 在顶（黑方），行 9 在底（红方，玩家）。
棋子：红 K帅 A仕 B相 N马 R车 C炮 P兵；黑 k将 a士 b象 n马 r车 c炮 p卒；'.' 空。
走法：((fr, fc), (tr, tc))。合法性含：马蹩腿、象塞眼不过河、士帅九宫、
兵过河横走、炮隔子吃、将帅不照面、不能送将（走后己方被将）。
对局结束：一方无合法走法（将死/困毙）即负。长将等重复局面不判（家庭对局简化）。
"""
import random

RED, BLACK = 0, 1
PIECE_NAME = {
    "K": "帅", "A": "仕", "B": "相", "N": "马", "R": "车", "C": "炮", "P": "兵",
    "k": "将", "a": "士", "b": "象", "n": "马", "r": "车", "c": "炮", "p": "卒",
}
INIT_BOARD = [
    list("rnbakabnr"),
    list("........."),
    list(".c.....c."),
    list("p.p.p.p.p"),
    list("........."),
    list("........."),
    list("P.P.P.P.P"),
    list(".C.....C."),
    list("........."),
    list("RNBAKABNR"),
]
PIECE_VALUE = {"K": 10000, "R": 900, "C": 450, "N": 400, "A": 200, "B": 200, "P": 100}

# ---------------------------------------------------------------------------
# 位置价值表（红方视角，行 0 顶=黑方底线；黑方评估时行镜像 9-r）。
# 数值参考传统象棋引擎的经典结论：马占中心/卧槽、炮镇中路、车占通线与卒林、
# 兵越河越值钱（原 P_BONUS 并入此处）。
# ---------------------------------------------------------------------------
PST = {
    "P": [
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
        [4, 6, 8, 12, 16, 12, 8, 6, 4],
        [6, 10, 14, 20, 26, 20, 14, 10, 6],
        [8, 14, 20, 28, 34, 28, 20, 14, 8],
        [10, 16, 24, 32, 40, 32, 24, 16, 10],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
    ],
    "N": [
        [0, -4, 0, 0, 0, 0, 0, -4, 0],
        [0, 2, 4, 4, 4, 4, 4, 2, 0],
        [4, 6, 8, 10, 10, 10, 8, 6, 4],
        [2, 8, 12, 14, 14, 14, 12, 8, 2],
        [4, 10, 14, 16, 16, 16, 14, 10, 4],
        [4, 8, 12, 14, 14, 14, 12, 8, 4],
        [2, 4, 8, 10, 10, 10, 8, 4, 2],
        [0, 2, 4, 4, 4, 4, 4, 2, 0],
        [0, 0, 2, 2, 2, 2, 2, 0, 0],
        [0, 0, 0, 2, 2, 2, 2, 0, 0],
    ],
    "R": [
        [8, 10, 10, 12, 14, 12, 10, 10, 8],
        [10, 14, 14, 16, 18, 16, 14, 14, 10],
        [10, 14, 16, 18, 20, 18, 16, 14, 10],
        [10, 14, 16, 20, 22, 20, 16, 14, 10],
        [10, 14, 16, 20, 22, 20, 16, 14, 10],
        [6, 10, 12, 14, 16, 14, 12, 10, 6],
        [4, 8, 10, 12, 14, 12, 10, 8, 4],
        [2, 6, 8, 10, 12, 10, 8, 6, 2],
        [0, 4, 6, 8, 10, 8, 6, 4, 0],
        [-2, 4, 6, 8, 8, 8, 6, 4, -2],
    ],
    "C": [
        [4, 4, 0, -4, -6, -4, 0, 4, 4],
        [2, 2, 0, -4, -6, -4, 0, 2, 2],
        [2, 2, 0, -4, -6, -4, 0, 2, 2],
        [2, 2, 0, -4, -6, -4, 0, 2, 2],
        [0, 0, 0, -2, -4, -2, 0, 0, 0],
        [0, 2, 4, 6, 10, 6, 4, 2, 0],      # 当头炮位
        [0, 0, 0, 2, 6, 2, 0, 0, 0],
        [0, 0, 0, 2, 8, 2, 0, 0, 0],
        [0, 0, 0, 2, 8, 2, 0, 0, 0],
        [0, 0, 0, 2, 8, 2, 0, 0, 0],
    ],
    "K": [
        [0] * 9, [0] * 9, [0] * 9, [0] * 9, [0] * 9, [0] * 9, [0] * 9,
        [-6, -6, -6, -8, -10, -8, -6, -6, -6],
        [-4, -4, -4, -6, -8, -6, -4, -4, -4],
        [-2, -2, -2, -4, -6, -4, -2, -2, -2],
    ],
    "A": [[0] * 9 for _ in range(10)],
    "B": [[0] * 9 for _ in range(10)],
}


def side_of(piece: str) -> int | None:
    if piece == ".":
        return None
    return RED if piece.isupper() else BLACK


def in_board(r, c):
    return 0 <= r < 10 and 0 <= c < 9


def in_palace(r, c, side):
    if not (3 <= c <= 5):
        return False
    return (0 <= r <= 2) if side == BLACK else (7 <= r <= 9)


def find_king(board, side):
    k = "K" if side == RED else "k"
    for r in range(10):
        for c in range(9):
            if board[r][c] == k:
                return r, c
    return None


class Game:
    def __init__(self):
        self.board = [row[:] for row in INIT_BOARD]
        self.turn = RED                     # 红先行
        self.hist = []                      # 已走过的局面 key（重复局面/长将判定用）
        self.rule_start_fen = None
        self.rule_moves = []
        self.halfmove_clock = 0             # 连续无吃子步数（自然限着判和用）
        self.zkey = self.compute_zkey()

    def compute_zkey(self):
        """从头算 Zobrist 键：棋子 + 轮走方（黑走时异或 _Z_SIDE）。"""
        z = _Z_SIDE if self.turn == BLACK else 0
        for r in range(10):
            for c in range(9):
                p = self.board[r][c]
                if p != ".":
                    z ^= _ZR[p][r][c]
        return z

    def pos_key(self):
        """局面键：棋盘 + 轮走方。"""
        return hash(("".join("".join(r) for r in self.board), self.turn))

    def play(self, mv):
        """真实走子（UI 层用）：先记录走前局面，再落子。搜索用 make/unmake 不记录。"""
        if getattr(self, "rule_start_fen", None) is None:
            from ..xiangqi_rules import fen
            self.rule_start_fen = fen(self.board, self.turn)
            self.rule_moves = []
        from ..xiangqi_rules import coordinate
        self.rule_moves.append(coordinate(mv))
        self.hist.append(self.pos_key())
        cap = self.make(mv)
        self.halfmove_clock = 0 if cap != "." else self.halfmove_clock + 1
        return cap

    def repeat_count(self) -> int:
        """当前局面在历史中出现的次数（含本次走子后调用）。"""
        return self.hist.count(self.pos_key()) + 1

    def is_natural_draw(self) -> bool:
        """自然限着：连续 120 步（60 回合）无吃子判和。"""
        return self.halfmove_clock >= 120

    def is_material_draw(self) -> bool:
        """保守子力和棋：无车马炮且无兵；单兵残局可能获胜，不能自动判和。"""
        pawns = 0
        for r in range(10):
            for c in range(9):
                p = self.board[r][c]
                if p == ".":
                    continue
                u = p.upper()
                if u in ("R", "C", "N"):
                    return False
                if u == "P":
                    pawns += 1
        return pawns == 0

    def piece(self, r, c):
        return self.board[r][c]

    def pseudo_moves(self, side):
        """该方全部伪合法走法（未过滤送将）。"""
        out = []
        for r in range(10):
            for c in range(9):
                p = self.board[r][c]
                if p == "." or side_of(p) != side:
                    continue
                out.extend(self._piece_moves(r, c, p))
        return out

    def _piece_moves(self, r, c, p):
        B = self.board
        side = side_of(p)
        up = -1 if side == RED else 1       # 红向上（行号减小）进攻
        moves = []

        def add(tr, tc):
            if in_board(tr, tc) and side_of(B[tr][tc]) != side:
                moves.append(((r, c), (tr, tc)))

        if p in ("K", "k"):
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                tr, tc = r + dr, c + dc
                if in_board(tr, tc) and in_palace(tr, tc, side):
                    add(tr, tc)
        elif p in ("A", "a"):
            for dr, dc in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                tr, tc = r + dr, c + dc
                if in_board(tr, tc) and in_palace(tr, tc, side):
                    add(tr, tc)
        elif p in ("B", "b"):
            for dr, dc in ((2, 2), (2, -2), (-2, 2), (-2, -2)):
                tr, tc = r + dr, c + dc
                er, ec = r + dr // 2, c + dc // 2
                own_half = (0 <= tr <= 4) if side == BLACK else (5 <= tr <= 9)
                if in_board(tr, tc) and own_half and B[er][ec] == ".":
                    add(tr, tc)
        elif p in ("N", "n"):
            for dr, dc, lr, lc in ((2, 1, 1, 0), (2, -1, 1, 0), (-2, 1, -1, 0), (-2, -1, -1, 0),
                                   (1, 2, 0, 1), (1, -2, 0, -1), (-1, 2, 0, 1), (-1, -2, 0, -1)):
                tr, tc = r + dr, c + dc
                if in_board(tr, tc) and B[r + lr][c + lc] == ".":
                    add(tr, tc)
        elif p in ("R", "r"):
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                tr, tc = r + dr, c + dc
                while in_board(tr, tc):
                    t = B[tr][tc]
                    if t == ".":
                        moves.append(((r, c), (tr, tc)))
                    else:
                        if side_of(t) != side:
                            moves.append(((r, c), (tr, tc)))
                        break
                    tr, tc = tr + dr, tc + dc
        elif p in ("C", "c"):
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                tr, tc, jumped = r + dr, c + dc, False
                while in_board(tr, tc):
                    t = B[tr][tc]
                    if not jumped:
                        if t == ".":
                            moves.append(((r, c), (tr, tc)))
                        else:
                            jumped = True
                    else:
                        if t != ".":
                            if side_of(t) != side:
                                moves.append(((r, c), (tr, tc)))
                            break
                    tr, tc = tr + dr, tc + dc
        elif p in ("P", "p"):
            add(r + up, c)
            crossed = (r <= 4) if side == RED else (r >= 5)
            if crossed:
                add(r, c + 1)
                add(r, c - 1)
        return moves

    def kings_facing(self):
        """将帅是否照面（照面=非法局面）。"""
        rk, bk = find_king(self.board, RED), find_king(self.board, BLACK)
        if not rk or not bk or rk[1] != bk[1]:
            return False
        c = rk[1]
        for r in range(bk[0] + 1, rk[0]):
            if self.board[r][c] != ".":
                return False
        return True

    def attacked(self, r, c, by):
        """(r,c) 格是否被 by 方攻击（士象够不到对方九宫，不用查）。"""
        B = self.board
        # 兵：正前方一格；过河兵的横向相邻
        pawn = "P" if by == RED else "p"
        fwd = -1 if by == RED else 1          # by 方兵的进攻方向
        if in_board(r - fwd, c) and B[r - fwd][c] == pawn:
            return True
        for dc in (-1, 1):
            pr, pc = r, c + dc
            if in_board(pr, pc) and B[pr][pc] == pawn:
                crossed = (pr <= 4) if by == RED else (pr >= 5)
                if crossed:
                    return True
        # 马：8 个马位 + 对应蹩腿
        horse = "N" if by == RED else "n"
        for dr, dc in ((2, 1), (2, -1), (-2, 1), (-2, -1), (1, 2), (1, -2), (-1, 2), (-1, -2)):
            hr, hc = r + dr, c + dc           # 马所在位
            if in_board(hr, hc) and B[hr][hc] == horse:
                # 蹩腿：马走"日"时腿在直向半格
                lr = hr - (dr // 2 if abs(dr) == 2 else 0)
                lc = hc - (dc // 2 if abs(dc) == 2 else 0)
                if B[lr][lc] == ".":
                    return True
        # 直线：车 / 将（照面）/ 炮（隔一子）
        rook = "R" if by == RED else "r"
        cannon = "C" if by == RED else "c"
        king = "K" if by == RED else "k"
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            tr, tc = r + dr, c + dc
            first = True
            while in_board(tr, tc):
                p = B[tr][tc]
                if p != ".":
                    if side_of(p) == by:
                        u = p.upper()
                        if first and (u == "R" or u == "K"):
                            return True       # 车攻 / 将帅照面
                        if not first and u == "C":
                            return True       # 炮隔子攻
                    if first:
                        first = False         # 继续找炮架后的炮
                    else:
                        break                 # 第二个子已查（非炮即止）
                tr, tc = tr + dr, tc + dc
        return False

    def in_check(self, side):
        """side 的将是否被将军（被吃/照面视作被将）。"""
        king = find_king(self.board, side)
        if not king:
            return True
        return self.attacked(*king, 1 - side)

    def legal_moves(self, side):
        """过滤送将/照面后的合法走法。"""
        out = []
        for mv in self.pseudo_moves(side):
            cap = self.make(mv)
            bad = self.in_check(side)
            self.unmake(mv, cap)
            if not bad:
                out.append(mv)
        return out

    def make(self, mv):
        """落子（真实走子/搜索试走）。返回被吃子（撤销时传回）。Zobrist 增量维护。"""
        (fr, fc), (tr, tc) = mv
        cap = self.board[tr][tc]
        p = self.board[fr][fc]
        z = self.zkey ^ _ZR[p][fr][fc] ^ _ZR[p][tr][tc] ^ _Z_SIDE   # 换手：轮走方分量翻转
        if cap != ".":
            z ^= _ZR[cap][tr][tc]
        self.zkey = z
        self.board[tr][tc] = p
        self.board[fr][fc] = "."
        self.turn = 1 - self.turn
        return cap

    def unmake(self, mv, cap):
        (fr, fc), (tr, tc) = mv
        p = self.board[tr][tc]
        z = self.zkey ^ _ZR[p][fr][fc] ^ _ZR[p][tr][tc] ^ _Z_SIDE   # 换手：轮走方分量翻转
        if cap != ".":
            z ^= _ZR[cap][tr][tc]
        self.zkey = z
        self.board[fr][fc] = p
        self.board[tr][tc] = cap
        self.turn = 1 - self.turn

    def has_legal(self, side):
        """是否存在合法着（存在即返回，供 is_over 早退）。"""
        for mv in self.pseudo_moves(side):
            cap = self.make(mv)
            bad = self.in_check(side)
            self.unmake(mv, cap)
            if not bad:
                return True
        return False

    def is_over(self):
        """当前走子方无合法着法 → 负。返回 (结束?, 胜方)。"""
        if not self.has_legal(self.turn):
            return True, 1 - self.turn
        return False, None


# ---------------------------------------------------------------------------
# AI：negamax + alpha-beta + 子力/位置评估
# ---------------------------------------------------------------------------

def evaluate(board) -> int:
    """红方视角分值：子力 + 位置价值 + 残局知识。"""
    s = 0
    big = {0: 0, 1: 0}      # 双方车马炮子力合计（残局判定）
    material = [0, 0]
    for r in range(10):
        for c in range(9):
            p = board[r][c]
            if p == ".":
                continue
            u = p.upper()
            v = PIECE_VALUE[u] + PST[u][r if p.isupper() else 9 - r][c]
            if p.isupper():
                s += v
                material[0] += PIECE_VALUE[u]
                if u in ("R", "C", "N"):
                    big[0] += PIECE_VALUE[u]
            else:
                s -= v
                material[1] += PIECE_VALUE[u]
                if u in ("R", "C", "N"):
                    big[1] += PIECE_VALUE[u]
    # 残局知识：大子少时兵价值放大、士象全防守方加分（车难破士象全）
    if big[0] + big[1] <= 1300:
        for r in range(10):
            for c in range(9):
                p = board[r][c]
                if p.upper() == "P" and p != ".":
                    pst = PST["P"][r if p.isupper() else 9 - r][c]
                    s += pst if p.isupper() else -pst
    return s


# ---------------------------------------------------------------------------
# Zobrist 置换表：增量局面哈希 + 搜索缓存
# ---------------------------------------------------------------------------
import random as _rnd

_ZR = {}
_zr_rng = _rnd.Random(20261004)
for _p in "KABNRCPkabnrcp":
    _ZR[_p] = [[_zr_rng.getrandbits(64) for _ in range(9)] for _ in range(10)]
_Z_SIDE = _zr_rng.getrandbits(64)   # 轮走方分量：同棋盘红走/黑走必须是不同键，否则置换表串分

TT_EXACT, TT_LOWER, TT_UPPER = 0, 1, 2
TT = {}          # zobrist(含轮走方) -> (depth, flag, score)
TT_MAX = 200_000  # 容量上限：超过即清空，防长时间对局内存无限增长


def order_moves(board, moves):
    """吃子优先排序（提升剪枝效率）。"""

    def score(mv):
        (fr, fc), (tr, tc) = mv
        cap = board[tr][tc]
        return PIECE_VALUE[cap.upper()] if cap != "." else 0

    return sorted(moves, key=score, reverse=True)


class SearchStopped(Exception):
    pass


def _check_search(game):
    import time
    cancel = getattr(game, "_search_cancel", None)
    deadline = getattr(game, "_search_deadline", None)
    if (cancel is not None and cancel.is_set()) or (deadline is not None and time.monotonic() >= deadline):
        raise SearchStopped()


def quiesce(game: Game, alpha: int, beta: int) -> int:
    """静态搜索：叶子节点继续搜吃子交换，消除'深度边缘看不见反吃'的水平线效应。"""
    _check_search(game)
    stand = evaluate(game.board)
    if game.turn == BLACK:
        stand = -stand
    if stand >= beta:
        return beta
    if stand > alpha:
        alpha = stand
    caps = [m for m in order_moves(game.board, game.pseudo_moves(game.turn))
            if game.piece(m[1][0], m[1][1]) != "."]
    for mv in caps:
        cap = game.make(mv)
        if game.in_check(1 - game.turn):        # 走完自己被将 = 非法，跳过
            game.unmake(mv, cap)
            continue
        try:
            v = -quiesce(game, -beta, -alpha)
        finally:
            game.unmake(mv, cap)
        if v >= beta:
            return beta
        if v > alpha:
            alpha = v
    return alpha


def search(game: Game, depth: int, alpha: int, beta: int, q: bool = False) -> int:
    """negamax + alpha-beta + 置换表（当前轮到 game.turn，返回该方视角分值）。
    q=True 时叶子节点接静态搜索（困难档专用棋力来源）。"""
    _check_search(game)
    if depth == 0:
        if q:
            return quiesce(game, alpha, beta)
        e = evaluate(game.board)
        return e if game.turn == RED else -e
    moves = game.legal_moves(game.turn)   # 将死判定与走法生成合一，省一次全盘扫描
    if not moves:
        return -100000 - depth            # 剩余 depth 越大=杀得越早，对被杀方越惨——逼 AI 选最快杀
    key = (game.zkey, q)   # 启用/禁用静态搜索的估值不能共用缓存
    hit = TT.get(key)
    if hit is not None and hit[0] >= depth:
        _, flag, sc = hit
        if flag == TT_EXACT:
            return sc
        if flag == TT_LOWER and sc > alpha:
            alpha = sc
        elif flag == TT_UPPER and sc < beta:
            beta = sc
        if alpha >= beta:
            return sc
    a0 = alpha
    best = -10 ** 9
    for mv in order_moves(game.board, moves):
        cap = game.make(mv)
        try:
            v = -search(game, depth - 1, -beta, -alpha, q)
        finally:
            game.unmake(mv, cap)
        if v > best:
            best = v
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    flag = TT_EXACT if a0 < best < beta else (TT_LOWER if best >= beta else TT_UPPER)
    if len(TT) >= TT_MAX:
        TT.clear()
    TT[key] = (depth, flag, best)
    return best


# 难度标定：depth / 静态搜索 / 评分噪声
# 困难档刻意只到"业余中上"：深度 3 + 静态搜索 + 保留半兵级噪声，可被爱好者战胜
DIFFICULTY = {
    0: (1, False, 120),     # 简单：一层 + 大噪声（常送兵、选次优）
    1: (2, False, 25),      # 中等：两层 + 小噪声
    2: (3, True, 12),       # 困难：三层 + 静态搜索（微噪声，偶有不精确）
}


def ai_move(game: Game, level: int = 1, cancel=None, time_limit=None):
    """level: 0 简单 / 1 中等 / 2 困难。
    迭代加深（浅层喂置换表）+ 时间上限 + 根层重复局面惩罚（治长将/长捉循环）。"""
    depth, use_q, noise = DIFFICULTY[level]
    moves = game.legal_moves(game.turn)
    if not moves:
        return None
    # 根节点重算键：外部直接改 board/turn（摆残局、测试）后增量键会失真，进而与别的局面串表
    game.zkey = game.compute_zkey()
    if len(TT) > TT_MAX:
        TT.clear()
    import time as _t
    t0 = _t.monotonic()
    limit = time_limit if time_limit is not None else (2.5 if level == 2 else 1.0)
    game._search_deadline = t0 + limit
    game._search_cancel = cancel
    best = moves[0]
    for d in range(1, depth + 1):
        cur_best, cur_v, stop = None, -10 ** 9, False
        for mv in order_moves(game.board, moves):
            if cur_best is not None and _t.monotonic() - t0 > limit:
                stop = True
                break
            cap = game.make(mv)
            try:
                v = -search(game, d - 1, -10 ** 9, 10 ** 9, use_q)
                rep = game.hist.count(game.pos_key())
            except SearchStopped:
                stop = True
                break
            finally:
                game.unmake(mv, cap)
            if rep >= 2:
                v = 0           # 第三次重复：与 UI 的和棋结果一致
            elif rep == 1:
                v -= 400        # 重演过一次，明显降分避免拉锯
            v += random.random() * noise
            if v > cur_v:
                cur_best, cur_v = mv, v
        if cur_best is not None:
            best = cur_best     # 该层完整（或至少出了一个结果）则采纳
        if stop:
            break               # 时间到：用最近完成层（更深未完成的结果不可靠，弃用）
    game._search_deadline = None
    game._search_cancel = None
    return None if cancel is not None and cancel.is_set() else best
