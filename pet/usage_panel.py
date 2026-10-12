# -*- coding: utf-8 -*-
"""Token 用量面板：深色卡片设计（参考用户的用量面板参考.png）。

布局：Hero 卡（今日用量大数字 + 本周占比进度条 + 调用次数/缓存命中徽章）
     → 模型分布（近7天，条形占比）→ 桌宠自身调用量小卡 → 数据源说明。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import usage_reader

CSS = """
QWidget { background: #17181c; color: #f4f4f5; font-family: 'Microsoft YaHei UI'; }
#card { background: #1f2127; border-radius: 14px; }
#modelBadge { background: rgba(52, 211, 153, 0.15); color: #34d399; border-radius: 9px;
              padding: 3px 10px; font-size: 12px; font-weight: 600; }
#bigNum { color: #ffffff; font-size: 34px; font-weight: 700; }
#subText { color: #8b8d98; font-size: 12px; }
#barTrack { background: #2a2c34; border-radius: 4px; }
#barFill { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #10b981, stop:1 #34d399);
           border-radius: 4px; }
#badgeAmber { background: rgba(245, 158, 11, 0.14); color: #f59e0b; border-radius: 8px;
              padding: 3px 10px; font-size: 12px; }
#badgeRed { background: rgba(239, 68, 68, 0.14); color: #ef4444; border-radius: 8px;
            padding: 3px 10px; font-size: 12px; }
#sectionTitle { color: #c5c7d0; font-size: 13px; font-weight: 600; }
#modelRow { background: #1b1d23; border-radius: 9px; }
#modelName { color: #d8dae2; font-size: 12px; }
#modelVal { color: #9ca0ab; font-size: 12px; }
#modelBarTrack { background: #2a2c34; border-radius: 3px; }
#modelBarFill { background: #4f7cff; border-radius: 3px; }
#petCard { background: rgba(79, 124, 255, 0.08); border-radius: 10px; }
#petText { color: #aeb6d6; font-size: 12px; }
#note { color: #5d5f6b; font-size: 11px; }
QPushButton#refresh { background: #26282f; color: #d8dae2; border: none; border-radius: 8px;
                      padding: 6px 16px; font-size: 12px; }
QPushButton#refresh:hover { background: #31343d; }
"""


def _fmt(n) -> str:
    n = float(n or 0)
    if n >= 1_000_000:
        s = f"{n / 1_000_000:.2f}".rstrip("0").rstrip(".")
        return f"{s}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{int(n)}"


def _fmt_full(n) -> str:
    return f"{int(n or 0):,}"


class Bar(QFrame):
    """横向进度条（track + 按比例的 fill）。"""

    def __init__(self, track_h=8, fill_color=None, parent=None):
        super().__init__(parent)
        self.setObjectName("barTrack")
        self.setFixedHeight(track_h)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._fill = QFrame(self)
        self._fill.setObjectName("barFill")
        if fill_color:
            self._fill.setStyleSheet(f"background: {fill_color}; border-radius: 3px;")
        self._fill.setFixedHeight(track_h)
        self._ratio = 0.0

    def set_ratio(self, r: float):
        self._ratio = max(0.0, min(1.0, r))
        self._apply()

    def _apply(self):
        self._fill.setGeometry(0, 0, max(int(self.width() * self._ratio), 0), self.height())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._apply()


class UsagePanel(QWidget):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Token 用量")
        self.setMinimumSize(420, 560)
        self.setStyleSheet(CSS)

        # ---- Hero 卡 ----
        hero = QFrame()
        hero.setObjectName("card")
        hero_v = QVBoxLayout(hero)
        hero_v.setContentsMargins(20, 18, 20, 18)
        hero_v.setSpacing(8)

        top = QHBoxLayout()
        self.model_badge = QLabel("GLM · 全模型")
        self.model_badge.setObjectName("modelBadge")
        top.addWidget(self.model_badge)
        top.addStretch(1)
        hero_v.addLayout(top)

        self.big_num = QLabel("0")
        self.big_num.setObjectName("bigNum")
        hero_v.addWidget(self.big_num)
        self.sub_text = QLabel("今日 · out of 本周 0 tokens")
        self.sub_text.setObjectName("subText")
        hero_v.addWidget(self.sub_text)

        self.bar = Bar(8)
        hero_v.addWidget(self.bar)

        badges = QHBoxLayout()
        self.badge_calls = QLabel("今日 0 次调用")
        self.badge_calls.setObjectName("badgeAmber")
        self.badge_cache = QLabel("缓存命中 --")
        self.badge_cache.setObjectName("badgeRed")
        badges.addWidget(self.badge_calls)
        badges.addSpacing(8)
        badges.addWidget(self.badge_cache)
        badges.addStretch(1)
        hero_v.addLayout(badges)

        # ---- 模型分布 ----
        sec1 = QLabel("模型分布（近 7 天）")
        sec1.setObjectName("sectionTitle")
        self.model_rows_v = QVBoxLayout()
        self.model_rows_v.setSpacing(6)

        # ---- 桌宠自身 ----
        pet = QFrame()
        pet.setObjectName("petCard")
        pet_h = QHBoxLayout(pet)
        pet_h.setContentsMargins(14, 10, 14, 10)
        self.pet_text = QLabel("桌宠自身：—")
        self.pet_text.setObjectName("petText")
        pet_h.addWidget(self.pet_text)
        pet_h.addStretch(1)

        note = QLabel(f"累计 {_fmt_full(0)} tokens · 数据源：zcode 本地数据库（只读）")
        note.setObjectName("note")
        self.note_label = note

        btn = QPushButton("刷新")
        btn.setObjectName("refresh")
        btn.clicked.connect(self.refresh)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        root.addWidget(hero)
        root.addWidget(sec1)
        root.addLayout(self.model_rows_v)
        root.addStretch(1)
        root.addWidget(pet)
        root.addWidget(note)
        root.addWidget(btn, 0, Qt.AlignRight)
        # 不在构造时 refresh：showEvent 每次打开都会刷新，构造时再查一次 sqlite 是重复开销

    def refresh(self):
        usage_reader._cache.pop(self.cfg["zcode_db_path"], None)   # 面板里看的是最新数据，跳过菜单用的短缓存
        d = usage_reader.zcode_usage(self.cfg["zcode_db_path"])
        if d.get("error"):
            self.big_num.setText("--")
            self.sub_text.setText(d["error"])
            self.bar.set_ratio(0)
            # 出错时清掉上一次的旧数字，避免误以为是当前数据
            self.badge_calls.setText("今日 -- 次调用")
            self.badge_cache.setText("缓存命中 --")
            self.note_label.setText("数据源：zcode 本地数据库（只读）")
        else:
            t, w = d["today"], d["week"]
            self.big_num.setText(_fmt(t["total"]))
            self.sub_text.setText(f"今日 · out of 本周 {_fmt(w['total'])} tokens")
            self.bar.set_ratio(t["total"] / w["total"] if w["total"] else 0)
            self.badge_calls.setText(f"今日 {t['calls']} 次调用")
            hit = t["cache_read"] / t["in"] if t["in"] else 0
            self.badge_cache.setText(f"缓存命中 {hit:.0%}")
            self.badge_cache.setObjectName("badgeRed" if hit < 0.5 else "modelBadge")
            # 改 objectName 后按新选择器重套全局样式（setStyleSheet("") 不保证重新 polish）
            self.badge_cache.style().unpolish(self.badge_cache)
            self.badge_cache.style().polish(self.badge_cache)
            self.note_label.setText(
                f"累计 {_fmt_full(d['total']['total'])} tokens · 数据源：zcode 本地数据库（只读）")
        # 模型行
        while self.model_rows_v.count():
            item = self.model_rows_v.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rows = d.get("models_7d") or []
        # 条长按 token 量对比（与右侧数字同口径）；此前用调用次数做分母，条几乎全部满格
        peak = max((r[2] + r[3] for r in rows), default=0) or 1
        for mname, calls, ti, to in rows:
            row = QFrame()
            row.setObjectName("modelRow")
            row.setFixedHeight(44)
            v = QVBoxLayout(row)
            v.setContentsMargins(12, 6, 12, 6)
            v.setSpacing(3)
            h1 = QHBoxLayout()
            lab = QLabel(mname)
            lab.setObjectName("modelName")
            val = QLabel(f"{_fmt(ti + to)} · {calls} 次")
            val.setObjectName("modelVal")
            h1.addWidget(lab)
            h1.addStretch(1)
            h1.addWidget(val)
            v.addLayout(h1)
            b = Bar(5, fill_color="#4f7cff")
            b.setObjectName("modelBarTrack")
            b.set_ratio((ti + to) / peak)
            v.addWidget(b)
            self.model_rows_v.addWidget(row)
        pet = usage_reader.pet_usage_summary()
        self.pet_text.setText(
            f"桌宠自身：今日 {_fmt(pet['today']['in'] + pet['today']['out'])} tokens"
            f"（{pet['today']['calls']} 次）· 累计 {_fmt(pet['total']['in'] + pet['total']['out'])}")

    def showEvent(self, ev):
        self.refresh()
        super().showEvent(ev)
