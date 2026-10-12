# -*- coding: utf-8 -*-
"""井字棋 —— 和清言对弈（清言 = O，minimax 完美棋力，玩家最多逼平）。

适配清言插件协议：TITLE + create(cfg, parent) -> QWidget
"""
import random

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import theme

TITLE = "井字棋"
DESCRIPTION = "三连成线即胜。清言棋力完美，能逼平她就很厉害了！"

LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))

PET_MOVE = ["看我这一手～", "嘿嘿，落子喽", "轮到我啦～"]
PET_BLOCK = ["才不让你赢！", "嘿嘿，看穿你了～", "这步可逃不过我的眼睛"]
PET_WIN = ["我赢啦我赢啦！(≧▽≦)", "嘿嘿，还差得远哦～"]
PET_DRAW = ["平局！主人好厉害，居然逼平我了～", "势均力敌呢，再来！"]
PET_LOSE = ["咦？！我居然输了…主人太强了吧！"]


def winner(b: str) -> str:
    """返回 'X'/'O'/''（无胜者）。"""
    for a, c, d in LINES:
        if b[a] != " " and b[a] == b[c] == b[d]:
            return b[a]
    return ""


def minimax(b: str, me: str, turn: str) -> int:
    """返回本步对 me 的分值：胜=1 平=0 负=-1（井字棋状态空间小，直接穷举）。"""
    w = winner(b)
    if w:
        return 1 if w == me else -1
    if " " not in b:
        return 0
    scores = []
    for i in range(9):
        if b[i] == " ":
            b = b[:i] + turn + b[i + 1:]
            scores.append(minimax(b, me, "O" if turn == "X" else "X"))
            b = b[:i] + " " + b[i + 1:]
    return max(scores) if turn == me else min(scores)


def best_move(b: str, me: str = "O") -> tuple[int, bool]:
    """清言的最佳着。返回 (位置, 是否阻挡——玩家下一步就要赢被我堵住)。"""
    opp = "X" if me == "O" else "O"
    # 阻挡判定：对方有立即取胜点且我下在那里
    opp_win_spots = [i for i in range(9) if b[i] == " "
                     and winner(b[:i] + opp + b[i + 1:]) == opp]
    best, best_score = -1, -2
    for i in range(9):
        if b[i] == " ":
            nb = b[:i] + me + b[i + 1:]
            score = minimax(nb, me, opp)
            if score > best_score:
                best, best_score = i, score
    is_block = best in opp_win_spots
    return best, is_block


def smart_move(b: str, me: str = "O") -> tuple[int, bool]:
    """中等棋力：能赢就赢、能堵就堵，其余随机（可用双威胁击败）。"""
    opp = "X" if me == "O" else "O"
    for i in range(9):
        if b[i] == " " and winner(b[:i] + me + b[i + 1:]) == me:
            return i, False
    for i in range(9):
        if b[i] == " " and winner(b[:i] + opp + b[i + 1:]) == opp:
            return i, True
    return random.choice([i for i in range(9) if b[i] == " "]), False


def lazy_move(b: str, me: str = "O") -> tuple[int, bool]:
    """简单棋力：能赢就赢（顺手），其余纯随机——陪玩送温暖档。"""
    for i in range(9):
        if b[i] == " " and winner(b[:i] + me + b[i + 1:]) == me:
            return i, False
    return random.choice([i for i in range(9) if b[i] == " "]), False


class _Cell(QPushButton):
    """棋格按钮：底子还是按钮（hover/边框/禁用态白拿），标记用自绘大图形。"""

    def __init__(self):
        super().__init__()
        self.mark = " "

    def set_mark(self, m):
        self.mark = m
        self.update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self.mark == " ":
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = self.width()
        m = int(side * 0.20)                       # 标记占格子 60%
        pen = QPen(QColor(theme.RED if self.mark == "X" else theme.GREEN),
                   max(6.0, side * 0.10))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        if self.mark == "X":                       # 玩家：红叉
            p.drawLine(m, m, side - m, side - m)
            p.drawLine(side - m, m, m, side - m)
        else:                                      # 清言：绿圈
            p.drawEllipse(QRectF(m, m, side - 2 * m, side - 2 * m))


class TicTacToe(QDialog):
    def __init__(self, cfg=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("和清言玩井字棋")
        self.setStyleSheet(f"QDialog {{ background: {theme.BG}; }}"
                           f"QPushButton {{ {theme.button()} font-size: 26px; }}")
        root = QVBoxLayout(self)
        self.board = " " * 9
        self.locked = False
        self._gen = 0               # 局号：重开后旧局挂起的 _pet_move 定时器作废
        self.score = {"win": 0, "lose": 0, "draw": 0}

        self.status = QLabel("你是 ✕（红叉），清言是 〇（绿圈）。点格子开始～")
        self.status.setStyleSheet(theme.label(theme.TEXT_DIM, 14))
        self.status.setAlignment(Qt.AlignCenter)
        root.addWidget(self.status)

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

        from PySide6.QtWidgets import QGridLayout
        grid = QGridLayout()
        grid.setSpacing(6)
        self.cells: list[_Cell] = []
        for i in range(9):
            btn = _Cell()
            btn.setFixedSize(84, 84)
            btn.clicked.connect(lambda _=False, i=i: self._click(i))
            grid.addWidget(btn, i // 3, i % 3)
            self.cells.append(btn)
        root.addLayout(grid)

        again = QPushButton("再来一局")
        again.setStyleSheet(theme.button(primary=True))
        again.setFixedHeight(36)
        again.clicked.connect(self._reset)
        root.addWidget(again)

    def _set_level(self, idx: int):
        self.level = idx
        for i, b in enumerate(self._level_btns):
            b.setChecked(i == idx)
            b.setStyleSheet(theme.button(primary=(i == idx)))

    def _say(self, text):
        self.status.setText(text)

    def _reset(self):
        self.board = " " * 9
        self.locked = False
        self._gen += 1
        for c in self.cells:
            c.set_mark(" ")
            c.setEnabled(True)
        w, l, d = self.score["win"], self.score["lose"], self.score["draw"]
        self._say(f"战绩 胜{w} / 负{l} / 平{d} —— 你是 ✕，先手～")
        self._pet_state("thinking")

    def _click(self, i):
        if self.locked or self.board[i] != " ":
            return
        self._put(i, "X")
        if self._check():
            return
        # 清言回手
        self.locked = True
        from PySide6.QtCore import QTimer
        gen = self._gen
        QTimer.singleShot(random.randint(350, 800), lambda: self._pet_move(gen))

    def _pet_move(self, gen=None):
        if gen is not None and gen != self._gen:
            return                      # 上一局的挂起回调，丢弃
        movers = (lazy_move, smart_move, best_move)
        pos, is_block = movers[self.level](self.board, "O")
        if pos < 0:
            self.locked = False
            return
        self._put(pos, "O")
        if is_block:
            self._say(random.choice(PET_BLOCK))
        else:
            self._say(random.choice(PET_MOVE))
        if self._check():
            return
        self.locked = False

    def _put(self, i, ch):
        self.board = self.board[:i] + ch + self.board[i + 1:]
        self.cells[i].set_mark(ch)
        self.cells[i].setEnabled(False)

    def _check(self) -> bool:
        w = winner(self.board)
        full = " " not in self.board
        if w == "X":
            self.score["win"] += 1
            self._say(random.choice(PET_LOSE))
            self._pet_state("lose")
        elif w == "O":
            self.score["lose"] += 1
            self._say(random.choice(PET_WIN))
            self._pet_state("win")
        elif full:
            self.score["draw"] += 1
            self._say(random.choice(PET_DRAW))
            self._pet_state("idle")
        else:
            return False
        self.locked = True
        return True



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


def create(cfg, parent=None):
    return TicTacToe(cfg, parent)
