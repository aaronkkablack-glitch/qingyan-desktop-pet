# -*- coding: utf-8 -*-
"""桌宠全局设置（独立窗口，右键/托盘菜单「⚙ 设置」入口）：子页面式。

页签：常规（开机自启 / 喝水提醒 / 桌宠大小滑块） + 关于（版本/作者/更新内容）。
保存后由 main 注入的流程触发 water.restart。聊天的专项设置在聊天窗的
SettingsDialog 里，各是各的。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from . import autostart, theme

APP_VERSION = "V1.0"
APP_AUTHOR = "不止黑色"
APP_NAME = "清言V1.0"

CHANGELOG = """\
V1.0（2026-10-05）
· 桌宠「清言」：精灵图动画八状态、立绘模式、呼吸式待机
· 定时喝水提醒 / 日程提醒（课表式，开始与结束均确认）
· GLM 对话：流式聊天、function calling（开应用等）、聊天记录持久化
· zcode 联动：zcode 工作中清言思考，结束庆祝；token 用量面板
· 互动游戏×4：井字棋 / 五子棋 / 象棋 / 斗地主（难度分级、悔棋、台词）
· 插件系统：互动插件/ 目录扩展第三方游戏
· 打包分享：单文件 exe + 便携数据；开机自启、应用别名可视化配置"""


class PetSettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("清言设置")
        # theme.tab() 是完整规则块，必须平铺拼接（嵌套花括号=非法 QSS，踩过三次）
        self.setStyleSheet(f"QDialog {{ background: {theme.BG}; }}"
                           f"QLabel {{ {theme.label(theme.TEXT_DIM, 13)} }}"
                           f"QCheckBox {{ color: {theme.TEXT_DIM}; }}"
                           f"QCheckBox::indicator {{ border: 1px solid {theme.TRACK};"
                           f" border-radius: 4px; background: {theme.CARD_ALT}; width: 15px;"
                           f" height: 15px; }}"
                           f"QCheckBox::indicator:checked {{ background: {theme.GREEN};"
                           f" border-color: {theme.GREEN}; }}"
                           f"QSpinBox {{ {theme.input_box()} }}"
                           + theme.tab())
        self.setMinimumWidth(460)

        tabs = QTabWidget()
        tabs.addTab(self._page_general(), "常规")
        tabs.addTab(self._page_about(), "关于")

        root = QVBoxLayout(self)
        root.addWidget(tabs)

        ok = QPushButton("保存并关闭")
        ok.setStyleSheet(theme.button(primary=True))
        ok.clicked.connect(self._save)
        cancel = QPushButton("取消")
        cancel.setStyleSheet(theme.button())
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

    # ---------- 页 1：常规 ----------

    def _page_general(self) -> QWidget:
        cfg = self.cfg
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(12)

        def section(title: str):
            """分组标题（强调色小字）+ 分割线。"""
            cap = QLabel(title)
            cap.setStyleSheet(theme.label(theme.GREEN, 12, 600))
            v.addWidget(cap)
            line = QLabel()
            line.setFixedHeight(1)
            line.setStyleSheet(f"background: {theme.TRACK}; border: none;")
            v.addWidget(line)

        def gap():
            v.addSpacing(6)

        section("启动")
        self.autostart_check = QCheckBox("开机自动启动清言")
        self.autostart_check.setChecked(autostart.is_enabled())
        v.addWidget(self.autostart_check)
        gap()

        section("外观")
        # 桌宠大小滑块：拖动实时预览（父窗口即桌宠），取消时还原
        self._pet = self.parent() if hasattr(self.parent(), "set_height") else None
        self._height_orig = int(cfg.get("pet_height", 400))
        hrow = QHBoxLayout()
        hrow.addWidget(QLabel("桌宠大小"))
        self.height_slider = QSlider(Qt.Horizontal)
        self.height_slider.setRange(200, 800)
        self.height_slider.setSingleStep(10)
        self.height_slider.setPageStep(50)
        self.height_slider.setValue(self._height_orig)
        self.height_label = QLabel(f"{self._height_orig} px")
        self.height_label.setStyleSheet(theme.label(theme.TEXT_MUTE, 12))
        self.height_slider.valueChanged.connect(self._on_height)
        hrow.addWidget(self.height_slider, 1)
        hrow.addWidget(self.height_label)
        v.addLayout(hrow)
        gap()

        section("提醒")
        self.water_check = QCheckBox("喝水提醒")
        self.water_check.setChecked(bool(cfg["water"].get("enabled")))
        v.addWidget(self.water_check)

        row = QHBoxLayout()
        row.addWidget(QLabel("间隔"))
        self.water_interval = QSpinBox()
        self.water_interval.setRange(5, 240)
        self.water_interval.setSuffix(" 分钟")
        self.water_interval.setValue(int(cfg["water"].get("interval_min", 45)))
        row.addWidget(self.water_interval)
        row.addSpacing(16)
        row.addWidget(QLabel("活跃时段"))
        self.water_start = QSpinBox()
        self.water_start.setRange(0, 23)
        self.water_start.setValue(int(cfg["water"].get("active_start", 9)))
        self.water_end = QSpinBox()
        self.water_end.setRange(0, 24)
        self.water_end.setSuffix(" 点")
        tip = "起点晚于终点表示跨夜（如 22 至 6）；起止相同表示全天"
        self.water_start.setToolTip(tip)
        self.water_end.setToolTip(tip)
        self.water_end.setValue(int(cfg["water"].get("active_end", 22)))
        row.addWidget(self.water_start)
        row.addWidget(QLabel("至"))
        row.addWidget(self.water_end)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)
        return page

    # ---------- 页 2：关于 ----------

    def _page_about(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(8)
        title = QLabel(f"{APP_NAME}")
        title.setStyleSheet(theme.label(theme.TEXT, 20, 700))
        v.addWidget(title)
        author = QLabel(f"作者：{APP_AUTHOR}")
        author.setStyleSheet(theme.label(theme.TEXT_DIM, 14))
        v.addWidget(author)
        v.addSpacing(6)
        head = QLabel("更新内容")
        head.setStyleSheet(theme.label(theme.TEXT, 13, 600))
        v.addWidget(head)
        body = QLabel(CHANGELOG)
        body.setWordWrap(True)
        body.setStyleSheet(theme.label(theme.TEXT_DIM, 12))
        v.addWidget(body)
        v.addStretch(1)
        return page

    # ---------- 行为 ----------

    def _on_height(self, val: int):
        """滑块实时预览：改配置并让桌宠立即变大小（不落盘，保存/取消统一收尾）。"""
        self.height_label.setText(f"{val} px")
        self.cfg["pet_height"] = val
        if self._pet:
            self._pet.set_height(val)

    def reject(self):
        """取消：把拖过的滑块尺寸还原（所见即所得的对称行为）。"""
        if int(self.cfg.get("pet_height", 400)) != self._height_orig:
            self.cfg["pet_height"] = self._height_orig
            if self._pet:
                self._pet.set_height(self._height_orig)
        super().reject()

    def _save(self):
        import copy
        old = copy.deepcopy(self.cfg.d)
        old_autostart = autostart.is_enabled()
        w = dict(self.cfg.get("water") or {})
        w.update({"enabled": self.water_check.isChecked(),
                  "interval_min": self.water_interval.value(),
                  "active_start": self.water_start.value(),
                  "active_end": self.water_end.value()})
        self.cfg["water"] = w
        ok, message = autostart.set_enabled(self.autostart_check.isChecked())
        try:
            if not ok:
                raise OSError(message)
            self.cfg.save()
        except OSError as e:
            self.cfg.d.clear()
            self.cfg.d.update(old)
            autostart.set_enabled(old_autostart)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "保存失败", str(e))
            return
        self.accept()
