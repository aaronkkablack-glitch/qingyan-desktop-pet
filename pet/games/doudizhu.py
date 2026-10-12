# -*- coding: utf-8 -*-
"""斗地主 —— 和清言、鲸鱼娘三人开一局。清言/鲸鱼娘由叫牌决定身份：
同一局里她可能是你的农民队友，也可能是地主对手。

适配清言插件协议：TITLE + create(cfg, parent) -> QWidget
"""
import random

from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from .. import theme
from .doudizhu_engine import (DECK, Move, ai_bid, ai_follow, ai_lead, beats, gen_moves,
                    parse_move, rank_label)

TITLE = "斗地主"
DESCRIPTION = "和清言、大肥鱼三人斗地主。叫分定地主，身份随机：清言可能是队友也可能是对手。"

NAMES = ("你", "清言", "大肥鱼")
PET_LINES = {
    "lead": ["出牌喽～", "这手怎么样～", "嘿嘿，看我的", "轮到我啦！"],
    "follow": ["压得住！", "接～", "跟一手"],
    "pass": ["要不起要不起～", "不要不要", "这手太大了，过～"],
    "bomb": ["炸！！轰隆～💥", "炸弹来咯！"],
    "bid": ["我叫 {n} 分！", "这牌可以一战！"],
    "bid_pass": ["这牌…叫不动，过～", "算了算了，不叫"],
    "win": ["赢啦赢啦！(≧▽≦)", "嘿嘿，赢了哦～"],
    "lose": ["呜…输了，下次一定！", "可恶，再来一局！"],
    "landlord": ["我是地主！都听我的～👑"],
    "farmer": ["农民联手，打倒地主！"],
}
# 大肥鱼（DeepSeek 拟人形象：胖鲸鱼娘，呆萌）：吃白饭/服务器繁忙/饭量大 梗
WHALE_LINES = {
    "lead": ["嗝…刚吃饱，出这张", "吃饱了才有力气打牌！出～", "这手牌下饭，出！", "边吃边打，出这张噜"],
    "follow": ["跟！（嘴里塞满了）", "这口我接得住～", "白饭不能停，牌也要跟！"],
    "pass": ["服务器繁忙…先过一下下", "嗝～吃不下了，要不起", "这把摆烂吃白饭，过～", "肚子太沉压不住，过"],
    "bomb": ["把饭喷出来了！！炸💥", "大招：干饭引爆！", "这颗米粒是炸弹！轰"],
    "bid": ["饭香扑鼻，叫 {n} 分！", "鲸鱼胃口，叫 {n}！", "吃白饭也要争气，叫 {n}"],
    "bid_pass": ["手抖（拿筷子拿的），不叫", "今天白饭没吃够，不叫", "嗝…太撑了，不叫了"],
    "win": ["赢啦！今天加鸡腿🍚", "嘿嘿，赢了奖励自己三碗饭", "鲸鱼胜利！干饭去咯～"],
    "lose": ["输了…回家吃白饭🥲", "没事，输了饭照吃", "呜…这把白吃了"],
    "landlord": ["地主大肥鱼要吃三份饭！🍚"],
    "farmer": ["和队友搭伙，蹭地主的白饭"],
}

CARD_W, CARD_H = 58, 82
AI_CARD_W = 44


def card_text(r: int) -> str:
    return {"16": "小王", "17": "大王"}.get(str(r)) or rank_label(r)


class _Seat:
    """一位玩家（0=你 1=清言 2=鲸鱼娘）。"""
    def __init__(self, idx):
        self.idx = idx
        self.hand = []
        self.is_landlord = False
        self.last_shown = Move.pass_move()      # 本"轮"展示的最近出牌
        self.bid = None


class Doudizhu(QWidget):
    def __init__(self, cfg=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("和清言、大肥鱼斗地主")
        # theme.button() 返回完整规则块，必须平铺拼接——嵌进 QPushButton{} 是嵌套花括号非法 QSS（按钮会退回系统黑字样式）
        self.setStyleSheet(f"QWidget {{ background: {theme.BG}; }}"
                           + theme.button()
                           + f" QPushButton:checked {{ background: {theme.GREEN_DEEP}; }}")
        self.setMinimumSize(880, 620)

        self.seats = [_Seat(i) for i in range(3)]
        self.phase = "bid"          # bid / play / over
        self.turn = -1
        self.last_move = Move.pass_move()      # 上一手有效出牌
        self.last_owner = -1
        self.pass_count = 0
        self.bottom = []
        self.bid_high = 0
        self.bid_winner = -1
        self.selected = set()       # 手牌选中的下标
        self.msg = ""

        root = QVBoxLayout(self)
        root.setSpacing(4)

        # 上排：两位 AI（名字 + 座位台词 + 牌数信息）
        top = QHBoxLayout()
        self.ai_widgets = {}
        for idx, align in ((2, "左"), (1, "右")):
            box = QWidget()
            v = QVBoxLayout(box)
            v.setSpacing(0)
            name = QLabel(NAMES[idx])
            name.setStyleSheet(theme.label(theme.TEXT, 15, 600))
            say = QLabel("")
            say.setWordWrap(True)
            say.setStyleSheet(theme.label(theme.AMBER, 12))
            info = QLabel("")
            info.setStyleSheet(theme.label(theme.TEXT_MUTE, 12))
            if idx == 1:      # 右侧（清言）右对齐
                name.setAlignment(Qt.AlignRight)
                say.setAlignment(Qt.AlignRight)
                info.setAlignment(Qt.AlignRight)
            v.addWidget(name)
            v.addWidget(say)
            v.addWidget(info)
            self.ai_widgets[idx] = {"box": box, "info": info, "say": say}
            top.addWidget(box, 1)
        root.addLayout(top)

        # 桌面区：出牌展示 + 状态
        self.table = _Table(self)
        self.table.setMinimumHeight(250)
        root.addWidget(self.table, 1)

        # 状态行
        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet(theme.label(theme.AMBER, 14))
        root.addWidget(self.status)

        # 按钮行
        self.btns = {}
        brow = QHBoxLayout()
        for key, text in (("play", "出牌"), ("pass", "不要"), ("hint", "提示")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=key: self._on_btn(k))
            brow.addWidget(b)
            self.btns[key] = b
        for n in (1, 2, 3):
            b = QPushButton(f"叫 {n}")
            b.clicked.connect(lambda _=False, n=n: self._on_bid(n))
            brow.addWidget(b)
            self.btns[f"bid{n}"] = b
        b = QPushButton("不叫")
        b.clicked.connect(lambda _=False: self._on_bid(0))
        brow.addWidget(b)
        self.btns["bid0"] = b
        brow.addStretch(1)
        b = QPushButton("再来一局")
        b.setStyleSheet(theme.button(primary=True))
        b.clicked.connect(self.new_game)
        brow.addWidget(b)
        self.btns["again"] = b
        root.addLayout(brow)

        # 手牌区
        self.hand_area = _HandArea(self)
        self.hand_area.setMinimumHeight(CARD_H + 30)
        root.addWidget(self.hand_area)

        # 看门狗：轮到 AI 却 2.5s 无进展（定时器丢失/回调异常）时补驱动，杜绝永久卡死
        import time as _time
        self._last_progress = _time.monotonic()
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(500)
        self._watchdog.timeout.connect(self._kick)
        self._watchdog.start()

        self.new_game()

    def _kick(self):
        import time as _time
        if self.phase == "over" or self.turn == 0:
            return
        if _time.monotonic() - self._last_progress > 2.5:
            self._last_progress = _time.monotonic()
            if self.phase == "bid":
                self._ai_bid()
            elif self.phase == "play":
                self._ai_play()

    # ---------------- 局面控制 ----------------

    def new_game(self):
        self._gen = getattr(self, "_gen", 0) + 1
        deck = DECK[:]
        random.shuffle(deck)
        self._pet_state("thinking")
        for i, s in enumerate(self.seats):
            s.hand = sorted(deck[i * 17:(i + 1) * 17])
            s.is_landlord = False
            s.last_shown = Move.pass_move()
            s.bid = None
        self.bottom = deck[51:]
        self.table.result = None      # 擦掉上一局的结算面板（否则新局还盖着旧"输/赢"大字）
        self.table.update()
        self.phase = "bid"
        self.last_move = Move.pass_move()
        self.last_owner = -1
        self.pass_count = 0
        self.bid_high = 0
        self.bid_winner = -1
        self.selected = set()
        self.turn = random.randrange(3)
        self.bid_starter = self.turn
        self.bid_count = 0
        self.msg = ""
        self._refresh(f"开始叫分（从{NAMES[self.turn]}起）")
        if self.turn != 0:
            self._later(600, self._ai_bid)

    def _later(self, ms, callback):
        gen, phase, turn = self._gen, self.phase, self.turn
        def run():
            if (gen, phase, turn) == (self._gen, self.phase, self.turn):
                callback()
        QTimer.singleShot(ms, run)

    def _say_to(self, who, text):
        """AI 发言显示到对应座位的人名下方；玩家/系统消息走底部状态栏。"""
        if who in (1, 2) and text:
            self.ai_widgets[who]["say"].setText(text)
        elif text:
            self.status.setText(text)

    def _refresh(self, msg=None):
        import time as _time
        self._last_progress = _time.monotonic()
        if msg is not None:
            self.msg = msg
        self.table.update()
        self.hand_area.update()
        for idx in (1, 2):
            s = self.seats[idx]
            role = "👑地主" if s.is_landlord else "🧑‍🌾农民"
            last = "过" if s.last_shown.is_pass else \
                " ".join(card_text(c) for c in s.last_shown.cards)
            self.ai_widgets[idx]["info"].setText(f"{role} · {len(s.hand)} 张 · {last}")
        self.status.setText(self.msg)
        bidding = self.phase == "bid"
        for k, b in self.btns.items():
            if k.startswith("bid"):
                b.setVisible(bidding)
            elif k == "again":
                b.setVisible(self.phase == "over")
            else:
                b.setVisible(not bidding and self.phase == "play")
        self.btns["play"].setEnabled(self.turn == 0 and self.phase == "play")
        self.btns["pass"].setEnabled(self.turn == 0 and self.phase == "play"
                                     and not self.last_move.is_pass)
        self.btns["hint"].setEnabled(self.turn == 0 and self.phase == "play")

    # ---------------- 叫分 ----------------

    def _on_bid(self, n):
        if self.phase != "bid" or self.turn != 0:
            return
        self._apply_bid(0, n)

    def _ai_bid(self):
        if self.phase != "bid":
            return
        who = self.turn
        hand = self.seats[who].hand
        n = ai_bid(hand, self.bid_high)
        self._apply_bid(who, n)

    def _apply_bid(self, who, n):
        s = self.seats[who]
        s.bid = n
        if n > self.bid_high:
            self.bid_high = n
            self.bid_winner = who
            if who:
                lines = PET_LINES if who == 1 else WHALE_LINES
                self._say_to(who, random.choice(lines["bid"]).format(n=n))
                self._refresh()
            else:
                self._refresh(f"你叫 {n} 分")
        else:
            if who:
                lines = PET_LINES if who == 1 else WHALE_LINES
                self._say_to(who, random.choice(lines["bid_pass"]))
                self._refresh()
            else:
                self._refresh("你选择不叫")
        self.bid_count += 1
        done = self.bid_count >= 3 or self.bid_high == 3
        if not done:
            self.turn = (self.turn + 1) % 3
            if self.turn == self.bid_starter and self.bid_count >= 3:
                done = True
        if done:
            if self.bid_winner < 0 or self.bid_high == 0:
                self._refresh("没人叫地主，重新发牌～")
                self._later(1200, self.new_game)
                return
            self._start_play()
            return
        if self.turn != 0:
            self._later(700, self._ai_bid)
        else:
            self._refresh(f"轮到你叫分（当前最高 {self.bid_high} 分）")

    def _start_play(self):
        lord = self.seats[self.bid_winner]
        lord.is_landlord = True
        lord.hand = sorted(lord.hand + self.bottom)
        # 地主宣言与农民抗议全部进各自座位台词栏；状态栏只留"谁成为地主+底牌"事实
        for idx in (1, 2):
            lines = PET_LINES if idx == 1 else WHALE_LINES
            if idx == self.bid_winner:
                self._say_to(idx, random.choice(lines["landlord"]))
            else:
                self._say_to(idx, random.choice(lines["farmer"]))
        self.phase = "play"
        self.turn = self.bid_winner
        for s in self.seats:
            s.last_shown = Move.pass_move()
        self._refresh(f"{NAMES[self.bid_winner]} 成为地主，底牌："
                      + " ".join(card_text(c) for c in self.bottom))
        if self.turn != 0:
            self._later(900, self._ai_play)

    # ---------------- 出牌 ----------------

    def _on_btn(self, key):
        if self.phase != "play" or self.turn != 0:
            return
        if key == "hint":
            self._hint()
            return
        if key == "pass":
            if self.last_move.is_pass:
                return
            self._commit(0, Move.pass_move())
            return
        if not self.selected:
            self._refresh("先点选要出的牌再按出牌～")
            return
        cards = [self.seats[0].hand[i] for i in sorted(self.selected)]
        mv = parse_move(cards, self.last_move)
        if not mv.type:
            self._refresh("这手牌不成牌型哦～")
            return
        if not beats(mv, self.last_move):
            self._refresh(f"压不住上一手（{NAMES[self.last_owner]} 的牌）")
            return
        self.selected.clear()
        self._commit(0, mv)

    def _hint(self):
        moves = gen_moves(self.seats[0].hand, self.last_move)
        if not moves:
            self._refresh("没有能出的牌，点「不要」吧")
            return
        # 提示给最小能出的（与 AI 同标准；ai_follow/ai_lead 已在文件顶部从 .doudizhu_engine 导入）
        mv = (ai_lead(self.seats[0].hand) if self.last_move.is_pass else
              ai_follow(self.seats[0].hand, self.last_move, False, 99, 99))
        if mv.is_pass and moves:
            mv = moves[0]
        want = mv.cards
        hand = self.seats[0].hand
        from collections import Counter
        need = Counter(want)
        self.selected = set()
        used = set()
        for i, c in enumerate(hand):
            if need.get(c, 0) > sum(1 for j in used if hand[j] == c):
                self.selected.add(i)
                used.add(i)
        self.hand_area.update()

    def _ai_play(self):
        if self.phase != "play" or self.turn == 0:
            return
        who = self.turn
        s = self.seats[who]
        if self.last_move.is_pass or self.last_owner == who:
            mv = ai_lead(s.hand)
            kind = "lead"
        else:
            # 阵营：地主 vs 两农民。出牌者与上一手出牌者同属农民 = 队友
            same_camp = (s.is_landlord == self.seats[self.last_owner].is_landlord)
            teammate = same_camp and not s.is_landlord
            enemy_min = min(len(x.hand) for i, x in enumerate(self.seats)
                            if i != who and x.is_landlord != s.is_landlord)
            mv = ai_follow(s.hand, self.last_move, teammate,
                           len(self.seats[self.last_owner].hand), enemy_min)
            kind = "follow" if not mv.is_pass else "pass"
        if mv.is_bomb:
            kind = "bomb"
        self._commit(who, mv, kind)

    def _commit(self, who, mv, kind=None):
        s = self.seats[who]
        if who != self.turn or self.phase != "play":
            return
        if not mv.is_pass:
            from collections import Counter
            previous = Move.pass_move() if self.last_owner == who else self.last_move
            parsed = parse_move(mv.cards, previous)
            if (parsed.type, parsed.rank, parsed.length) != (mv.type, mv.rank, mv.length) \
                    or not beats(parsed, previous) or Counter(mv.cards) - Counter(s.hand):
                self._refresh("出牌状态不一致，已拒绝这手牌")
                return
        elif self.last_move.is_pass or self.last_owner == who:
            return
        if not mv.is_pass:
            from collections import Counter
            for c in Counter(mv.cards).elements():
                s.hand.remove(c)
            self.last_move = mv
            self.last_owner = who
            self.pass_count = 0
        else:
            self.pass_count += 1
        s.last_shown = mv
        if kind is None:
            kind = "pass" if mv.is_pass else ("bomb" if mv.is_bomb else "lead")
        lines = PET_LINES if who == 1 else (WHALE_LINES if who == 2 else PET_LINES)
        say = "" if who == 0 else random.choice(lines[kind])
        if say:
            self._say_to(who, say)
        if not s.hand:
            self._finish(who)
            return
        if self.pass_count >= 2:
            self.last_move = Move.pass_move()      # 一圈没人要，重新自由出
            self.pass_count = 0
            self.turn = self.last_owner
            if self.turn != 0:
                self._later(800, self._ai_play)
            self._refresh(f"没人要，{NAMES[self.last_owner]} 继续出牌")
            return
        self.turn = (self.turn + 1) % 3
        if self.turn != 0:
            self._later(random.randint(500, 1000), self._ai_play)
            self._refresh()
        else:
            self._refresh("轮到你出牌")

    def _finish(self, winner):
        self.phase = "over"
        lord_win = self.seats[winner].is_landlord
        you = self.seats[0]
        you_win = (you.is_landlord and lord_win) or ((not you.is_landlord) and (not lord_win))
        qingyan = self.seats[1]
        qy_win = (qingyan.is_landlord and lord_win) or \
            ((not qingyan.is_landlord) and (not lord_win))
        for idx in (1, 2):
            s = self.seats[idx]
            s_win = (s.is_landlord and lord_win) or ((not s.is_landlord) and (not lord_win))
            line_set = PET_LINES if idx == 1 else WHALE_LINES
            self._say_to(idx, random.choice(line_set["win" if s_win else "lose"]))
        self.table.result = {
            "text": "🎉 你赢了！" if you_win else "😅 你输了",
            "detail": f"{'地主' if lord_win else '农民'}阵营获胜 · "
                      f"{'你是地主' if you.is_landlord else '你是农民'}",
            "leftover": " ｜ ".join(
                f"{NAMES[i]} 剩 [{ ' '.join(card_text(c) for c in s.hand) or '无' }]"
                for i, s in enumerate(self.seats) if s.hand),
        }
        self._refresh("牌局结束——点「再来一局」再战！")
        self._pet_state("win" if qy_win else "lose")   # 清言阵营胜=庆祝 / 负=出错
        self.table.update()

    def _pet_state(self, state):
        """向桌宠播联动动作；钩子由主程序注入，缺失则忽略。"""
        h = getattr(self, "pet_hooks", None)
        if h:
            try:
                h(state)
            except Exception:
                pass

    def closeEvent(self, ev):
        self._gen += 1
        self._watchdog.stop()
        self._pet_state("idle")
        super().closeEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)

    def paintEvent(self, ev):
        pass


# ---------------------------------------------------------------------------
# 桌面区：三家的出牌展示 + 结果
# ---------------------------------------------------------------------------

class _Table(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.game = parent
        self.result = None

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#1d3529"))   # 牌桌毛毡绿
        p.setPen(QPen(QColor("#2c4a3b"), 2))
        p.drawRoundedRect(self.rect().adjusted(4, 4, -4, -4), 10, 10)
        g = self.game
        # 左：鲸鱼娘（2）出牌 中：你的出牌 右：清言（1）
        zones = {2: (0.0, 0.32), 0: (0.34, 0.66), 1: (0.68, 1.0)}
        for idx, (a, b) in zones.items():
            x0 = self.width() * a
            x1 = self.width() * b
            s = g.seats[idx]
            p.setPen(QColor(theme.TEXT_MUTE))
            p.drawText(int(x0) + 8, 22, NAMES[idx])
            mv = s.last_shown
            if mv.is_pass and g.phase == "play":
                p.setPen(QColor(theme.TEXT_MUTE))
                p.drawText(int(x0) + 8, 48, "不要")
            elif not mv.is_pass:
                self._draw_cards(p, int(x0) + 8, 40, mv.cards, AI_CARD_W)
                if g.phase == "play" and not g.last_move.is_pass and idx == g.last_owner:
                    p.setPen(QColor(theme.AMBER))
                    f = QFont("Microsoft YaHei UI", 9, 700)
                    p.setFont(f)
                    p.drawText(int(x0) + 8, 40 + int(AI_CARD_W * 1.42) + 18, "▸ 上一手")
            if g.turn == idx and g.phase == "play":
                p.setPen(QColor(theme.GREEN))
                p.drawText(int((x0 + x1) / 2) - 16, 22, "●出牌")
        if g.phase == "bid" and g.turn >= 0:
            p.setPen(QColor(theme.AMBER))
            p.drawText(self.rect().adjusted(0, self.height() - 30, 0, 0),
                       Qt.AlignHCenter, f"叫分中… 当前最高：{g.bid_high} 分（{NAMES[g.bid_winner] if g.bid_winner >= 0 else '无人'}）")
        if self.result:
            p.setPen(QColor(theme.GREEN if "赢" in self.result["text"] else theme.RED))
            f = QFont("Microsoft YaHei UI", 20, 700)
            p.setFont(f)
            p.drawText(self.rect().adjusted(0, -40, 0, 0), Qt.AlignCenter,
                       self.result["text"])
            p.setFont(QFont("Microsoft YaHei UI", 11))
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(self.rect().adjusted(0, 20, 0, 0), Qt.AlignCenter,
                       self.result["detail"])
            if self.result.get("leftover"):
                p.setFont(QFont("Microsoft YaHei UI", 10))
                p.setPen(QColor(theme.TEXT_MUTE))
                p.drawText(self.rect().adjusted(0, 60, 0, 0), Qt.AlignCenter,
                           self.result["leftover"])

    def _draw_cards(self, p, x, y, cards, w):
        h = int(w * 1.42)
        overlap = max(6, w - 22)
        for i, c in enumerate(cards):
            draw_card(p, x + i * overlap, y, c, w, h)


def draw_card(p: QPainter, x: int, y: int, rank: int, w=CARD_W, h=CARD_H, sel=False):
    """zcode 风格卡牌：黑底、白字点数、中央白色大 Z（王牌金 Z）。"""
    p.save()
    r = QRectF(x, y, w, h)
    p.setPen(QPen(QColor("#4a4d58") if sel else QColor("#3a3d47"), 1.5 if sel else 1))
    king = rank in (16, 17)
    p.setBrush(QColor("#20232a") if sel else QColor("#14161a"))
    p.drawRoundedRect(r, 6, 6)
    king_color = (QColor("#e8b93c") if rank == 16 else QColor("#ef4444")) if king else None
    label = "JK" if king else card_text(rank)      # 王牌角标 JK：小王金 / 大王红
    p.setPen(king_color or QColor("#f4f4f5"))
    p.setFont(QFont("Segoe UI", int(w * 0.24), 700))
    p.drawText(r.adjusted(5, 3, 0, 0), Qt.AlignLeft | Qt.AlignTop, label)
    # 中央大 Z（zcode logo 风；王牌同色：小王金 Z / 大王红 Z）
    p.setPen(king_color or QColor("#f4f4f5"))
    p.setFont(QFont("Segoe UI", int(w * 0.46), 900))
    p.drawText(r.adjusted(0, 4, 0, -4), Qt.AlignCenter, "Z")
    p.restore()


class _HandArea(QWidget):
    """玩家手牌：paintEvent 绘制，点击选中（选中上浮）。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.game = parent

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hand = self.game.seats[0].hand
        sel = self.game.selected
        n = len(hand)
        if n == 0:
            return
        overlap = min(CARD_W - 14, max(24, (self.width() - CARD_W) // max(n - 1, 1)))
        total = CARD_W + overlap * (n - 1)
        x0 = max(0, (self.width() - total) // 2)
        for i, c in enumerate(hand):
            y = 12 if i in sel else 22
            draw_card(p, x0 + i * overlap, y, c, CARD_W, CARD_H, i in sel)

    def mousePressEvent(self, ev):
        hand = self.game.seats[0].hand
        n = len(hand)
        if not n or self.game.phase != "play" or self.game.turn != 0:
            return
        overlap = min(CARD_W - 14, max(24, (self.width() - CARD_W) // max(n - 1, 1)))
        total = CARD_W + overlap * (n - 1)
        x0 = max(0, (self.width() - total) // 2)
        pos = ev.position().toPoint()
        if not (0 <= pos.y() <= CARD_H + 24):
            return
        # 命中：从右往左找（后面的牌盖在右边）
        for i in range(n - 1, -1, -1):
            cx = x0 + i * overlap
            if cx <= pos.x() <= cx + CARD_W:
                if i in self.game.selected:
                    self.game.selected.discard(i)
                else:
                    self.game.selected.add(i)
                self.update()
                return


def create(cfg, parent=None):
    return Doudizhu(cfg, parent)
