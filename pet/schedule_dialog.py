# -*- coding: utf-8 -*-
"""日程管理对话框：时间骨架固定（每天同一套块），直接在「工作计划」列填内容。

列：标题 / 工作计划 / 星期(0-6) / 日期 / 开始 / 结束 / 提醒(分)。
提醒语义：-1 = 静默（学习块）；0 = 到点提醒；N = 提前 N 分钟提醒。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
import uuid

from .config import SCHEDULE_PATH
from .schedule_store import valid_hm
from . import theme

COLS = ["标题", "工作计划", "星期(0-6)", "日期", "开始", "结束", "提醒(分)"]


class ScheduleDialog(QWidget):
    def __init__(self, store: "ScheduleStore", parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("日程管理")
        self.resize(760, 440)
        self.setStyleSheet(f"""
            QWidget {{ background: {theme.BG}; color: {theme.TEXT_DIM};
                       font-family: 'Microsoft YaHei UI', 'Segoe UI'; }}
            {theme.table()}
            {theme.scrollbar()}
            """)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        tip = QLabel("工作计划留空只显示标题；星期填 0-6（0=周一），日期填 YYYY-MM-DD，星期和日期二选一，"
                     "都留空=每天。开始晚于结束表示跨午夜。提醒填 -1=无提前提醒，0=到点提醒。改动要点「保存」。")
        tip.setWordWrap(True)
        tip.setStyleSheet(theme.label(theme.TEXT_MUTE, 12))

        btn_add = QPushButton("➕ 添加")
        btn_add.setStyleSheet(theme.button())
        btn_add.clicked.connect(self._add_row)
        btn_del = QPushButton("🗑 删除选中行")
        btn_del.setStyleSheet(theme.button(danger=True))
        btn_del.clicked.connect(self._del_rows)
        btn_open = QPushButton("📂 打开文件")
        btn_open.setStyleSheet(theme.button())
        btn_open.clicked.connect(self._open_file)
        btn_save = QPushButton("💾 保存")
        btn_save.setStyleSheet(theme.button(primary=True))
        btn_save.clicked.connect(self._save)

        btns = QHBoxLayout()
        btns.addWidget(btn_add)
        btns.addWidget(btn_del)
        btns.addWidget(btn_open)
        btns.addStretch(1)
        btns.addWidget(btn_save)

        root = QVBoxLayout(self)
        root.addWidget(tip)
        root.addWidget(self.table, 1)
        root.addLayout(btns)
        self.load()

    def load(self):
        self.table.setRowCount(0)
        for e in self.store.entries:
            r = self.table.rowCount()
            self.table.insertRow(r)
            plan = e.get("plan") or e.get("note", "")  # 旧数据备注迁移为计划
            vals = [e.get("title", ""), plan, ",".join(map(str, e.get("days") or [])),
                    e.get("date") or "", e.get("start", ""), e.get("end", ""),
                    str(e.get("remind_before_min", 5))]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if c == 0:
                    # 整条原始数据挂在首列：保存时保留表格不展示的字段（note 等）
                    item.setData(Qt.UserRole, dict(e))
                self.table.setItem(r, c, item)

    def _add_row(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem("新块"))
        self.table.setItem(r, 4, QTableWidgetItem("09:00"))
        self.table.setItem(r, 5, QTableWidgetItem("10:00"))
        self.table.setItem(r, 6, QTableWidgetItem("-1"))

    def _del_rows(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def _open_file(self):
        import os
        import subprocess
        os.makedirs(os.path.dirname(SCHEDULE_PATH), exist_ok=True)
        subprocess.Popen(["notepad.exe", SCHEDULE_PATH])

    def _msg(self, icon, title, text):
        """深色消息框（原生 QMessageBox 不吃父样式表）。"""
        box = QMessageBox(icon, title, text, parent=self)
        box.setStyleSheet(f"""
            QMessageBox {{ background: {theme.CARD}; color: {theme.TEXT}; }}
            QLabel {{ color: {theme.TEXT}; background: transparent; font-size: 13px; }}
            QPushButton {{ {theme.button()} }}
        """)
        box.exec()

    def _save(self):
        entries = []
        for r in range(self.table.rowCount()):
            def cell(c):
                it = self.table.item(r, c)
                return it.text().strip() if it else ""
            title = cell(0)
            if not title:
                continue
            try:
                remind = int(cell(6) or 0)
            except ValueError:
                self._msg(QMessageBox.Warning, "格式错误", f"第 {r+1} 行提醒数值不对：{cell(6)}")
                return
            try:
                days = [int(x.strip()) for x in cell(2).split(",") if x.strip()]
            except ValueError:
                self._msg(QMessageBox.Warning, "格式错误", f"第 {r+1} 行星期格式不对：{cell(2)}")
                return
            if any(day < 0 or day > 6 for day in days) or len(set(days)) != len(days):
                self._msg(QMessageBox.Warning, "格式错误", f"第 {r+1} 行星期必须是 0-6 且不能重复")
                return
            date = cell(3) or None
            if date:
                try:
                    import datetime as dt
                    dt.date.fromisoformat(date)
                except ValueError:
                    self._msg(QMessageBox.Warning, "格式错误", f"第 {r+1} 行日期必须是 YYYY-MM-DD")
                    return
            if days and date:
                self._msg(QMessageBox.Warning, "格式错误", f"第 {r+1} 行星期和日期只能填写一个")
                return
            start, end = cell(4) or "09:00", cell(5) or "10:00"
            for label, val in (("开始", start), ("结束", end)):
                if not valid_hm(val):
                    self._msg(QMessageBox.Warning, "格式错误",
                              f"第 {r+1} 行{label}时间必须是 HH:MM（如 09:30）：{val}")
                    return
            if start == end:
                self._msg(QMessageBox.Warning, "格式错误", f"第 {r+1} 行开始和结束时间不能相同")
                return
            meta_item = self.table.item(r, 0)
            meta = meta_item.data(Qt.UserRole) if meta_item else None
            entry = dict(meta) if isinstance(meta, dict) else {}
            entry.update({
                "id": entry.get("id") or uuid.uuid4().hex[:8],
                "title": title, "plan": cell(1),
                "days": days, "date": date,
                "start": start, "end": end,
                "remind_before_min": remind,
            })
            entries.append(entry)
        try:
            self.store.save(entries)
        except OSError as e:
            self._msg(QMessageBox.Critical, "保存失败", f"日程没有保存成功：{e}")
            return
        self.load()  # 回填新行生成的 id，再次保存时保持不变（提醒去重依赖 id）
        self._msg(QMessageBox.Information, "已保存", f"共 {len(entries)} 条日程已生效。")
