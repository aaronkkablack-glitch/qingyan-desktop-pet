# -*- coding: utf-8 -*-
"""五子棋 —— 和清言对弈（15 路，玩家执黑先手，清言白子，启发式攻防评分 AI）。

适配清言插件协议：TITLE + create(cfg, parent) -> QWidget
AI 思路：对每个空点按八个方向统计双方连子形态打分（活四/冲四/活三…），
取"我方进攻分 + 对方威胁分（防守）"最高者。够陪玩，不是棋类引擎。
"""
import random

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import theme

TITLE = "五子棋"
DESCRIPTION = "15 路五连成线。你执黑先手，清言执白。"

N = 15
PET_MOVE = ["看我这一手～", "嗯…下这里！", "接招～", "嘿嘿，落子喽"]
PET_WIN = ["五连！我赢啦～(≧▽≦)", "嘿嘿，主人的棋还有破绽哦～"]
PET_LOSE = ["呜…主人五连了，好厉害！", "败了败了，主人棋艺高超！"]


def in_board(x, y):
    return 0 <= x < N and 0 <= y < N


def line_len(board, x, y, dx, dy, ch):
    """从 (x,y) 沿 (dx,dy) 数连续 ch 的个数（不含自身）。"""
    n = 0
    x, y = x + dx, y + dy
    while in_board(x, y) and board[y][x] == ch:
        n += 1
        x, y = x + dx, y + dy
    return n


def line_open(board, x, y, dx, dy, ch):
    """该方向延伸后末端是否为空（活）。"""
    n = line_len(board, x, y, dx, dy, ch)
    ex, ey = x + dx * (n + 1), y + dy * (n + 1)
    return in_board(ex, ey) and board[ey][ex] == " "


def score_point(board, x, y, ch) -> float:
    """在 (x,y) 落 ch 的价值：四方向连子形态评分。"""
    total = 0.0
    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        a = line_len(board, x, y, dx, dy, ch)
        b = line_len(board, x, y, -dx, -dy, ch)
        cnt = a + b + 1
        if cnt >= 5:
            total += 100000                       # 直接五连
        elif cnt == 4:
            total += 10000 if (line_open(board, x, y, dx, dy, ch)
                               or line_open(board, x, y, -dx, -dy, ch)) else 500   # 活四/冲四
        elif cnt == 3:
            total += 1000                          # 活三按宽松计
        elif cnt == 2:
            total += 100
        total += cnt * 2
    return total


def ai_move(board, level: int = 1) -> tuple[int, int]:
    """清言落子。level: 0 简单 / 1 中等（进攻分+0.9×防守分）/ 2 困难（强防守+必胜必堵）。
    返回 (x, y)。"""
    # 困难：显式必胜点（自己落子即五连）优先
    if level == 2:
        for y in range(N):
            for x in range(N):
                if board[y][x] == " ":
                    board[y][x] = "O"
                    win = check_win(board, x, y)
                    board[y][x] = " "
                    if win:
                        return x, y
        for y in range(N):                      # 显式必堵点（对方落子即五连）
            for x in range(N):
                if board[y][x] == " ":
                    board[y][x] = "X"
                    win = check_win(board, x, y)
                    board[y][x] = " "
                    if win:
                        return x, y
    def_w, ring, pick = {0: (0.35, 1, 6), 1: (0.9, 2, 3), 2: (1.4, 2, 1)}[level]
    scored = []
    occupied = [(x, y) for y in range(N) for x in range(N) if board[y][x] != " "]
    if not occupied:
        return N // 2, N // 2
    for y in range(N):
        for x in range(N):
            if board[y][x] != " ":
                continue
            if not any(in_board(x + dx, y + dy) and board[y + dy][x + dx] != " "
                       for dx in range(-ring, ring + 1) for dy in range(-ring, ring + 1)):
                continue                            # 只看已有棋子附近，省计算
            s = (score_point(board, x, y, "O") + def_w * score_point(board, x, y, "X")
                 + random.random() * 10)
            scored.append((s, x, y))
    if not scored:
        return N // 2, N // 2
    scored.sort(reverse=True)
    s, x, y = random.choice(scored[:pick])         # 简单档从 top6 随机（会漏堵），困难取最优
    return x, y


def check_win(board, x, y) -> bool:
    ch = board[y][x]
    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        if line_len(board, x, y, dx, dy, ch) + line_len(board, x, y, -dx, -dy, ch) + 1 >= 5:
            return True
    return False


class Gomoku(QDialog):
    CELL = 34

    def __init__(self, cfg=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("和清言玩五子棋")
        self.setStyleSheet(f"QDialog {{ background: {theme.BG}; }}")
        self.board = [[" "] * N for _ in range(N)]
        self.over = False
        self.locked = False         # 清言思考中：锁住玩家输入，防连点下两子
        self._gen = 0               # 局号：重开后旧局挂起的 AI 定时器作废
        self._msg = ""

        root = QVBoxLayout(self)
        self.status = QLabel("你执黑先行，点交叉点落子～")
        self.status.setStyleSheet(theme.label(theme.TEXT_DIM, 14))
        self.status.setAlignment(Qt.AlignCenter)
        root.addWidget(self.status)

        from PySide6.QtWidgets import QHBoxLayout
        lv_row = QHBoxLayout()
        lv_lab = QLabel("清言棋力：")
        lv_lab.setStyleSheet(theme.label(theme.TEXT_MUTE, 12))
        lv_row.addWidget(lv_lab)
        self.level = 1
        self._level_btns = []
        for idx, name in enumerate(("随意", "认真", "全力")):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setFixedHeight(30)
            b.clicked.connect(lambda _=False, i=idx: self._set_level(i))
            lv_row.addWidget(b)
            self._level_btns.append(b)
        lv_row.addStretch(1)
        root.addLayout(lv_row)
        self._set_level(1)

        self.canvas = _Board(self)
        self.canvas.setMinimumSize(N * self.CELL, N * self.CELL)
        self.canvas.mousePressEvent = lambda ev: self._click(ev)
        root.addWidget(self.canvas)

        again = QPushButton("再来一局")
        again.setStyleSheet(theme.button(primary=True))
        again.clicked.connect(self._reset)
        root.addWidget(again)

    def _set_level(self, idx: int):
        self.level = idx
        for i, b in enumerate(self._level_btns):
            b.setChecked(i == idx)
            b.setStyleSheet(theme.button(primary=(i == idx)))

    def _reset(self):
        self.board = [[" "] * N for _ in range(N)]
        self.over = False
        self.locked = False
        self._gen += 1
        self.status.setText("你执黑先行，点交叉点落子～")
        self._pet_state("thinking")
        self.canvas.update()

    def _click(self, ev):
        if self.over or self.locked:
            return
        pos = ev.position().toPoint()
        gx = round((pos.x() - self.canvas.pad) / self.CELL)
        gy = round((pos.y() - self.canvas.pad) / self.CELL)
        if not in_board(gx, gy) or self.board[gy][gx] != " ":
            return
        self._put(gx, gy, "X")
        if self._end(gx, gy, PET_LOSE):
            return
        self.status.setText("清言思考中…")
        self.locked = True
        from PySide6.QtCore import QTimer
        gen = self._gen
        QTimer.singleShot(random.randint(400, 900), lambda: self._pet(gen))

    def _pet(self, gen=None):
        if gen is not None and gen != self._gen:
            return                      # 上一局的挂起回调，丢弃
        self.locked = False
        if self.over:
            return
        x, y = ai_move(self.board, self.level)
        if not in_board(x, y):
            return
        self._put(x, y, "O")
        self.status.setText(random.choice(PET_MOVE))
        self._end(x, y, PET_WIN)

    def _put(self, x, y, ch):
        self.board[y][x] = ch
        self.canvas.update()

    def _end(self, x, y, lines) -> bool:
        if check_win(self.board, x, y):
            self.over = True
            self.status.setText(random.choice(lines))
            # lines==PET_WIN 是清言五连（她赢），PET_LOSE 是玩家五连
            self._pet_state("win" if lines is PET_WIN else "lose")
        elif all(c != " " for row in self.board for c in row):
            self.over = True
            self.status.setText("下满了，平局～")
            self._pet_state("idle")
        return self.over

    def _pet_state(self, state):
        """向桌宠播联动动作；钩子由主程序注入，缺失则忽略。"""
        h = getattr(self, "pet_hooks", None)
        if h:
            try:
                h(state)
            except Exception:
                pass

    def closeEvent(self, ev):
        self._pet_state("idle")
        super().closeEvent(ev)


class _Board(QWidget):
    """棋盘绘制：深色底、网格线、黑白子。"""

    def __init__(self, game):
        super().__init__(game)
        self.game = game
        self.pad = 24
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.CARD_ALT))
        g, cell, pad = self.game, Gomoku.CELL, self.pad
        p.setPen(QPen(QColor(theme.TRACK), 1))
        for i in range(N):
            x = pad + i * cell
            p.drawLine(x, pad, x, pad + (N - 1) * cell)
            p.drawLine(pad, x, pad + (N - 1) * cell, x)
        # 天元与星位
        p.setBrush(QColor(theme.TEXT_MUTE))
        for sx, sy in ((3, 3), (11, 3), (7, 7), (3, 11), (11, 11)):
            p.drawEllipse(QRectF(pad + sx * cell - 2.5, pad + sy * cell - 2.5, 5, 5))
        for y in range(N):
            for x in range(N):
                ch = g.board[y][x]
                if ch == " ":
                    continue
                cx, cy = pad + x * cell, pad + y * cell
                p.setBrush(QColor("#111318") if ch == "X" else QColor("#f4f4f5"))
                p.setPen(QPen(QColor(theme.TEXT_MUTE), 1))
                p.drawEllipse(QRectF(cx - 12, cy - 12, 24, 24))



def create(cfg, parent=None):
    return Gomoku(cfg, parent)
