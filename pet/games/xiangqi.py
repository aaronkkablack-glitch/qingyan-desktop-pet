# -*- coding: utf-8 -*-
"""中国象棋 —— 和清言对弈。你执红先行，清言执黑（alpha-beta AI，三档棋力）。

适配清言插件协议：TITLE + create(cfg, parent) -> QWidget
"""
import copy
import random
import threading

from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from .. import theme
from .xiangqi_engine import BLACK, PIECE_NAME, RED, TT, Game, ai_move

_UNSET = object()

TITLE = "象棋"
DESCRIPTION = "和清言下中国象棋。你执红先行，清言执黑，三档棋力。"

CELL = 52
PAD = 42

PET_LINES = {
    "move": ["接招～", "看这步！", "嘿嘿，走这里", "轮到我啦～"],
    "check": ["将军！接招～♞", "将军！看你怎么应～", "嘿嘿，将军喽！"],      # 清言将军玩家
    "checked": ["被、被将了？！让我看看…", "好险好险…差点中招", "唔…这一军有点狠…", "别得意！看我挡住～"],   # 玩家将军清言
    "capture_big": ["吃掉～不谢！", "这个子我收下啦！", "嘿嘿，到手～"],
    "capture_king_piece": ["嘿嘿，你的车车没了～", "大车车归我啦～"],   # 仅真吃车时用
    "captured": ["啊！我的子！", "呜…痛痛痛", "你好狠心…"],
    "win": ["赢啦赢啦！(≧▽≦)", "棋高一筹～嘿嘿", "这局我赢了哦！"],
    "lose": ["呜…输了，再来！", "好厉害…我认输", "下局我要认真了！"],
}


def _draw_piece(p: QPainter, cx, cy, piece, radius=22, hl=False):
    """圆形棋子：红=深红底白字，黑=深黑底白字。"""
    is_red = piece.isupper()
    p.save()
    p.setPen(QPen(QColor("#e8b93c" if hl else ("#8a2f2a" if is_red else "#3a3d47")), 2.2 if hl else 1.4))
    p.setBrush(QColor("#a03a30" if is_red else "#1d2026"))
    p.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
    p.setPen(QColor("#ffe9d6" if is_red else "#e8eaf0"))
    p.setFont(QFont("Microsoft YaHei UI", 15, 700))
    p.drawText(QRectF(cx - radius, cy - radius - 1, radius * 2, radius * 2),
               Qt.AlignCenter, PIECE_NAME[piece])
    p.restore()


class _Board(QWidget):
    def __init__(self, game_widget):
        super().__init__(game_widget)
        self.g = game_widget
        self.setMinimumSize(PAD * 2 + 8 * CELL, PAD * 2 + 9 * CELL)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#241a10"))          # 木色棋盘
        wood = QColor("#3a2a18")
        p.setPen(QPen(wood, 2))
        p.drawRoundedRect(self.rect().adjusted(6, 6, -6, -6), 10, 10)
        line = QColor("#c9a86a")
        p.setPen(QPen(line, 1.4))

        def X(c):
            return PAD + c * CELL

        def Y(r):
            return PAD + r * CELL

        # 横线 10 条
        for r in range(10):
            p.drawLine(X(0), Y(r), X(8), Y(r))
        # 竖线：上下两段（中间楚河汉界断开），边线整条
        for c in range(9):
            if c in (0, 8):
                p.drawLine(X(c), Y(0), X(c), Y(9))
            else:
                p.drawLine(X(c), Y(0), X(c), Y(4))
                p.drawLine(X(c), Y(5), X(c), Y(9))
        # 九宫斜线
        for top in (0, 7):
            p.drawLine(X(3), Y(top), X(5), Y(top + 2))
            p.drawLine(X(5), Y(top), X(3), Y(top + 2))
        # 楚河汉界
        p.setPen(QColor("#d8bd85"))
        p.setFont(QFont("Microsoft YaHei UI", 16, 600))
        p.drawText(QRectF(X(0), Y(4), 4 * CELL, CELL), Qt.AlignCenter, "楚 河")
        p.drawText(QRectF(X(4), Y(4), 4 * CELL, CELL), Qt.AlignCenter, "汉 界")

        g = self.g
        # 选中与合法落点
        if g.selected:
            (r, c) = g.selected
            p.setPen(QPen(QColor(theme.GREEN), 2))
            p.drawEllipse(QRectF(X(c) - 25, Y(r) - 25, 50, 50))
            for mv in g.cur_moves:
                tr, tc = mv[1]
                cx, cy = X(tc), Y(tr)
                if g.game.piece(tr, tc) != ".":
                    p.setPen(QPen(QColor(theme.RED), 2.4))
                    p.drawEllipse(QRectF(cx - 24, cy - 24, 48, 48))
                else:
                    p.setBrush(QColor(theme.GREEN))
                    p.setPen(Qt.NoPen)
                    p.drawEllipse(QRectF(cx - 5, cy - 5, 10, 10))
        # 棋子
        for r in range(10):
            for c in range(9):
                pc = g.game.piece(r, c)
                if pc != ".":
                    hl = g.selected == (r, c)
                    _draw_piece(p, X(c), Y(r), pc, hl=hl)
        # 上一步痕迹
        if g.last_mv:
            (fr, fc), (tr, tc) = g.last_mv
            p.save()
            p.setPen(QPen(QColor(theme.AMBER), 1.6))
            p.setBrush(Qt.NoBrush)   # 不清画刷会把方框画成实心青块（画落点时残留的绿色画刷）遮住棋子
            for (rr, cc) in ((fr, fc), (tr, tc)):
                p.drawRect(QRectF(X(cc) - 26, Y(rr) - 26, 52, 52))
            p.restore()

    def mousePressEvent(self, ev):
        g = self.g
        if g.game.turn != RED or g.over:
            return
        pos = ev.position().toPoint()
        c = round((pos.x() - PAD) / CELL)
        r = round((pos.y() - PAD) / CELL)
        if not (0 <= r < 10 and 0 <= c < 9) or abs(pos.x() - (PAD + c * CELL)) > 24 \
                or abs(pos.y() - (PAD + r * CELL)) > 24:
            return
        pc = g.game.piece(r, c)
        if g.selected and ((r, c) in [m[1] for m in g.cur_moves]):
            g.player_move((g.selected, (r, c)))
            return
        if pc != "." and pc.isupper():
            g.selected = (r, c)
            g.cur_moves = [m for m in g.game.legal_moves(RED) if m[0] == (r, c)]
        else:
            g.selected = None
            g.cur_moves = []
        self.update()


class Xiangqi(QWidget):
    _ai_done = Signal(int, object)   # (局号, 着法或 None)：后台搜索完成

    def __init__(self, cfg=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("和清言下象棋")
        self.setStyleSheet(f"QWidget {{ background: {theme.BG}; }}"
                           + theme.button()
                           + f" QPushButton:checked {{ background: {theme.GREEN_DEEP}; }}")
        self.game = Game()
        self.selected = None
        self.cur_moves = []
        self.last_mv = None
        self.over = False
        self.level = 1
        self.move_log = []          # [(mv, cap)] 悔棋用
        self._rules_warned = False  # 本局 judge 是否失败过（失败时状态栏提示）
        self._gen = 0               # 局号：新局/关窗递增，后台 AI 结果按局号丢弃过时的
        self._ai_busy = False
        self._search_cancel = threading.Event()
        self._ai_done.connect(self._on_ai_done)   # 跨线程信号：自动排队回 UI 线程

        root = QVBoxLayout(self)
        root.setSpacing(4)
        # 清言发言栏 + 状态
        self.pet_say = QLabel("你执红先行，我执黑后手～请多指教！")
        self.pet_say.setWordWrap(True)
        self.pet_say.setStyleSheet(theme.label(theme.AMBER, 13))
        root.addWidget(self.pet_say)
        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet(theme.label(theme.TEXT_DIM, 13))
        root.addWidget(self.status)

        self.board = _Board(self)
        root.addWidget(self.board, 1)

        brow = QHBoxLayout()
        lv = QLabel("清言棋力：")
        lv.setStyleSheet(theme.label(theme.TEXT_MUTE, 12))
        brow.addWidget(lv)
        self._lv_btns = []
        for idx, name in enumerate(("随意", "认真", "全力")):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setFixedHeight(30)
            b.clicked.connect(lambda _=False, i=idx: self._set_level(i))
            brow.addWidget(b)
            self._lv_btns.append(b)
        self._set_level(1)
        brow.addStretch(1)
        undo_btn = QPushButton("悔棋")
        undo_btn.clicked.connect(self.undo)
        brow.addWidget(undo_btn)
        self.undo_btn = undo_btn
        again = QPushButton("再来一局")
        again.setStyleSheet(theme.button(primary=True))
        again.clicked.connect(self.new_game)
        brow.addWidget(again)
        root.addLayout(brow)
        self._refresh_status()

    def _set_level(self, idx):
        self.level = idx
        for i, b in enumerate(self._lv_btns):
            b.setChecked(i == idx)
            b.setStyleSheet(theme.button(primary=(i == idx)))

    def new_game(self):
        self._search_cancel.set()
        self.game = Game()
        self.selected = None
        self.cur_moves = []
        self.last_mv = None
        self.over = False
        self.move_log = []          # 清空上局悔棋记录（否则悔棋会在新棋盘上 unmake 旧着法）
        self._rules_warned = False
        if not self._ai_busy:
            TT.clear()              # 新局清空搜索置换表，防跨局无限增长（后台搜索中则交给 TT_MAX 兜底）
        self._gen += 1              # 上局还在后台搜索的结果作废
        self._ai_busy = False
        self.status.setStyleSheet(theme.label(theme.TEXT_DIM, 13))   # 撤掉上局结算的大字样式
        self.pet_say.setText("新的一局！你执红先行～")
        self._pet_state("thinking")
        self._refresh_status()
        self.board.update()

    def _pet_state(self, state):
        """向桌宠播联动动作（thinking/done/error/idle）；钩子由主程序注入，缺失则忽略。"""
        h = getattr(self, "pet_hooks", None)
        if h:
            try:
                h(state)
            except Exception:
                pass

    def _refresh_status(self):
        self.undo_btn.setEnabled(not self.over and self.game.turn == RED
                                 and len(self.move_log) >= 2)
        if self.over:
            return
        warn = "（⚠ 规则裁决暂不可用，长将/长捉不会判定）" if self._rules_warned else ""
        if self.game.turn == RED:
            self.status.setText("轮到你（红方）" + (" —— 你被将军了！" if self.game.in_check(RED) else "") + warn)
        else:
            self.status.setText("清言思考中…" + (" —— 将军！" if self.game.in_check(BLACK) else "") + warn)

    def _say(self, key):
        self.pet_say.setText(random.choice(PET_LINES[key]))

    def player_move(self, mv):
        if self.over or self.game.turn != RED:
            return
        cap = self.game.piece(mv[1][0], mv[1][1])
        clock_before = self.game.halfmove_clock
        self.game.play(mv)
        self.move_log.append((mv, cap, clock_before))
        self.selected = None
        self.cur_moves = []
        self.last_mv = mv
        if cap != "." and cap.upper() in ("R", "C", "N"):
            self._say("captured")          # 清言的大子被吃（"啊！我的子！"）
        over, winner = self.game.is_over()
        self.board.update()
        if over:
            self._finish(winner)
            return
        if self._adjudicate():
            return
        checked = self.game.in_check(BLACK)
        if checked:
            self._say("checked")        # 玩家将军清言：紧张应对的口吻（不是"将军！接招"的得意）
        self._refresh_status()
        gen = self._gen
        QTimer.singleShot(random.randint(400, 900), lambda: self._start_ai(gen))

    def _start_ai(self, gen):
        """后台线程搜索（困难档最长约 2.5 秒，放 UI 线程会冻住窗口和桌宠动画）。
        搜索的是 Game 的深拷贝：主线程的棋盘在此期间只读，悔棋/新局通过局号作废结果。"""
        if gen != self._gen or self.over or self.game.turn != BLACK:
            return
        self._ai_busy = True
        self._refresh_status()
        snapshot, level = copy.deepcopy(self.game), self.level
        self._search_cancel = threading.Event()
        cancel = self._search_cancel

        def work():
            try:
                mv = ai_move(snapshot, level, cancel=cancel)
            except Exception as e:      # 引擎异常不能让线程静默吞掉、棋局卡在"思考中"
                print(f"[xiangqi] AI 搜索失败: {e}")
                mv = None
            self._ai_done.emit(gen, mv)

        threading.Thread(target=work, daemon=True).start()

    def _on_ai_done(self, gen, mv):
        if gen != self._gen:
            return                      # 新局/关窗后的旧结果：丢弃
        self._ai_busy = False
        self._pet_move(mv)

    def _pet_move(self, mv=_UNSET):
        """落 AI 着法；不传 mv 时同步搜索（测试直接驱动用）。"""
        if self.over or self.game.turn != BLACK:
            return
        if mv is _UNSET:
            mv = ai_move(self.game, self.level)
        elif mv is not None and mv not in self.game.legal_moves(BLACK):
            mv = ai_move(self.game, self.level)   # 防御：局面已变，结果不再合法则同步重算
        if mv is None:
            self._finish(RED)
            return
        cap = self.game.piece(mv[1][0], mv[1][1])
        clock_before = self.game.halfmove_clock
        self.game.play(mv)
        self.move_log.append((mv, cap, clock_before))
        self.last_mv = mv
        over, winner = self.game.is_over()
        self.board.update()
        if over:
            self._finish(winner)
            return
        if self._adjudicate():
            return
        if cap != "." and cap.upper() in ("R", "C", "N"):
            # 台词与被吃子匹配：只有真吃到车才说"车车没了"（用户反馈的误导点）
            self._say("capture_king_piece" if cap.upper() == "R" else "capture_big")
        elif self.game.in_check(RED):
            self._say("check")
        else:
            self._say("move")
        self._refresh_status()

    def undo(self):
        """悔棋：撤销最近一整轮（你的一步 + 清言的一步），回到你上次行棋前。"""
        if self.over or self.game.turn != RED or len(self.move_log) < 2 or self._ai_busy:
            return
        for _ in range(2):
            mv, cap, clock = self.move_log.pop()
            self.game.unmake(mv, cap)
            self.game.hist.pop()          # 同步撤销 play() 记录的局面 key（重复判定不受污染）
            if self.game.rule_moves:
                self.game.rule_moves.pop()
            self.game.halfmove_clock = clock   # 无吃子计数同步还原
        self.selected = None
        self.cur_moves = []
        self.last_mv = self.move_log[-1][0] if self.move_log else None
        self.pet_say.setText("好吧，这次就放主人一马~")
        self._refresh_status()
        self.board.update()

    def _check_draw(self):
        """其他和棋态：自然限着 / 子力和棋。返回 (清言台词, 状态文案) 或 None。"""
        if self.game.is_natural_draw():
            return "六十回合都没吃子…和了吧～", "🤝 60 回合无吃子，自然限着判和"
        if self.game.is_material_draw():
            return "谁也杀不动谁啦，握手握手～", "🤝 双方均无子力将死对方，判和"
        return None

    def _adjudicate(self):
        from ..xiangqi_rules import game_result
        try:
            result = game_result(self.game)
        except (OSError, RuntimeError, ValueError) as e:
            # judge 已内部重试过一次仍失败（缺文件 / 被杀软拦截 / FEN 非法）。
            # 不再把整局直接判死：回退到 Python 层的限着/子力和棋判断，局面继续；
            # 状态栏提示一次，下一步会再次尝试裁决。
            print(f"[xiangqi] 规则裁决不可用: {e}")
            self._rules_warned = True
            fallback = self._check_draw()
            if fallback:
                self._finish(None, fallback[0], fallback[1])
                return True
            return False
        self._rules_warned = False
        if result == "draw":
            self._finish(None, "按程序棋规，这局和棋啦～", "🤝 程序棋规判和")
            return True
        if result in ("red", "black"):
            self._finish(RED if result == "red" else BLACK)
            return True
        return False

    def _finish(self, winner, pet_line=None, status_line=None):
        self.over = True
        if winner is None:
            self.pet_say.setText(pet_line or "来回重复…这局算平啦～")
            self.status.setText((status_line or "🤝 三次重复局面，判和") + "，点「再来一局」")
            self.status.setStyleSheet(theme.label(theme.AMBER, 15, 700))
            self._pet_state("idle")      # 和棋：桌宠回待机
            self.board.update()
            return
        you_win = winner == RED
        self._pet_state("win" if not you_win else "lose")   # 清言执黑：她赢=庆祝，你赢=出错
        self.pet_say.setText(random.choice(PET_LINES["win" if not you_win else "lose"]))
        self.status.setText("🎉 你赢了！点「再来一局」再战" if you_win
                            else "清言获胜～点「再来一局」复仇")
        self.status.setStyleSheet(theme.label(theme.GREEN if you_win else theme.RED, 15, 700))
        self.board.update()

    def closeEvent(self, ev):
        self._search_cancel.set()
        self._gen += 1               # 作废还在路上的 AI 结果
        self._pet_state("idle")      # 关窗：游戏结束，桌宠回待机
        super().closeEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)


def create(cfg, parent=None):
    return Xiangqi(cfg, parent)
