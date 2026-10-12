# -*- coding: utf-8 -*-
"""聊天接口设置对话框：API Key / API 地址 / 模型 / 思考深度 / max_tokens。

分享版用户不碰 config.json 的唯一入口；api_base 可改 = 任何 OpenAI 兼容服务
（GLM / DeepSeek / 千问兼容模式等）都能接。保存写入 Config 引用（GlmClient 每次
请求现读，保存即生效）。
"""
import json
import os
import re
import threading
import time
import urllib.request
import copy
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QRadioButton, QSpinBox,
                               QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .config import ASSETS_DIR, DATA_DIR, DEFAULTS
from .net import DIRECT_OPENER

try:  # 白嫖通道默认回退模型以代理模块为准；导入失败时与 config 默认保持一致
    from freelane.freelane import DEFAULT_FALLBACK as _FL_DEFAULT_FALLBACK
except Exception:
    _FL_DEFAULT_FALLBACK = "space-bunny-free"

EFFORTS = ["low", "high", "max", "off"]  # off = 不发 thinking 字段（接非 GLM 模型用）


class SettingsDialog(QDialog):
    test_done = Signal(bool, str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self._live_cfg = cfg
        self.cfg = copy.deepcopy(cfg.d if hasattr(cfg, "d") else dict(cfg))
        self._pending_avatar = None
        self._avatar_reset = False
        self.setWindowTitle("设置")
        # theme.tab() 返回完整规则块，必须平铺拼接——嵌进 QTabWidget{} 会变嵌套花括号非法 QSS
        self.setStyleSheet(f"QDialog {{ background: {theme.BG}; }}"
                           f"QLabel {{ {theme.label(theme.TEXT_DIM, 13)} }}"
                           f"QCheckBox {{ color: {theme.TEXT_DIM}; }}"
                           f"QCheckBox::indicator {{ border: 1px solid {theme.TRACK};"
                           f" border-radius: 4px; background: {theme.CARD_ALT}; width: 15px;"
                           f" height: 15px; }}"
                           f"QCheckBox::indicator:checked {{ background: {theme.GREEN};"
                           f" border-color: {theme.GREEN}; }}"
                           f"QRadioButton {{ color: {theme.TEXT_DIM}; }}"
                           f"QRadioButton::indicator {{ border: 1px solid {theme.TRACK};"
                           f" border-radius: 7px; background: {theme.CARD_ALT}; width: 13px;"
                           f" height: 13px; }}"
                           f"QRadioButton::indicator:checked {{ background: {theme.GREEN};"
                           f" border-color: {theme.GREEN}; }}"
                           + theme.tab())
        self.setMinimumWidth(480)

        # ---- 页 1：接口 ----
        api_page = QWidget()
        v1 = QVBoxLayout(api_page)
        v1.setSpacing(8)

        fl = cfg.get("freelane") or {}
        fl_enabled = bool(fl.get("enabled"))
        fl_custom = fl.get("custom") or {}
        # 白嫖通道开启时，自定义字段显示"上次的自定义配置"（快照），而不是本地代理值
        if fl_enabled:
            seed_key = str(fl_custom.get("api_key") or "")
            seed_base = str(fl_custom.get("api_base") or DEFAULTS["api_base"])
            seed_model = str(fl_custom.get("chat_model") or DEFAULTS["chat_model"])
        else:
            seed_key = cfg.get("api_key", "")
            seed_base = cfg.get("api_base", "")
            seed_model = cfg.get("chat_model", "")

        v1.addWidget(QLabel("模型通道"))
        chan_row = QHBoxLayout()
        self.chan_freelane = QRadioButton("白嫖通道（本地免费）")
        self.chan_custom = QRadioButton("自定义 API（GLM / DeepSeek 等）")
        chan_row.addWidget(self.chan_freelane)
        chan_row.addWidget(self.chan_custom)
        chan_row.addStretch(1)
        v1.addLayout(chan_row)
        self.chan_hint = QLabel("")
        self.chan_hint.setWordWrap(True)
        self.chan_hint.setStyleSheet(theme.label(theme.TEXT_MUTE, 12))
        v1.addWidget(self.chan_hint)

        # ---- 自定义 API 组（勾"自定义 API"时才显示）----
        self.custom_box = QWidget()
        vc = QVBoxLayout(self.custom_box)
        vc.setContentsMargins(0, 0, 0, 0)
        vc.setSpacing(8)

        self.key_label = QLabel("API Key（开放平台 Key，形如 id.secret）")
        vc.addWidget(self.key_label)
        key_row = QHBoxLayout()
        self.key_edit = QLineEdit(seed_key)
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setStyleSheet(theme.input_box())
        self.key_edit.setPlaceholderText("在此粘贴 Key")
        self.show_key = QCheckBox("显示")
        self.show_key.toggled.connect(
            lambda on: self.key_edit.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password))
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.show_key)
        vc.addLayout(key_row)

        self.base_label = QLabel("API 地址（OpenAI 兼容 base，换服务商改这里）")
        vc.addWidget(self.base_label)
        self.base_edit = QLineEdit(seed_base)
        self.base_edit.setStyleSheet(theme.input_box())
        self.base_edit.setPlaceholderText("https://open.bigmodel.cn/api/paas/v4")
        vc.addWidget(self.base_edit)

        self.model_label = QLabel("模型（下拉可选，也可直接输入其他模型名）")
        vc.addWidget(self.model_label)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems([m for m in cfg.get("chat_models", [])
                                  if not m.endswith("-free")])
        self.model_combo.setCurrentText(seed_model)
        self.model_combo.setStyleSheet(theme.combo())
        vc.addWidget(self.model_combo)

        effort_row = QHBoxLayout()
        effort_row.addWidget(QLabel("思考深度"))
        self.effort_combo = QComboBox()
        self.effort_combo.addItems(EFFORTS)
        self.effort_combo.setCurrentText(cfg.get("thinking_effort", "low"))
        self.effort_combo.setStyleSheet(theme.combo())
        self.effort_combo.setToolTip("GLM-5.3 系必须思考（选档位）；off=不发送该参数，"
                                     "接 DeepSeek 等其他模型时选 off")
        effort_row.addWidget(self.effort_combo)
        effort_row.addStretch(1)
        vc.addLayout(effort_row)
        v1.addWidget(self.custom_box)

        # ---- 白嫖通道组（勾"白嫖通道"时才显示）----
        self.fl_box = QWidget()
        vf = QVBoxLayout(self.fl_box)
        vf.setContentsMargins(0, 0, 0, 0)
        vf.setSpacing(8)

        self.fl_model_label = QLabel("白嫖模型（上游名单见 http://127.0.0.1:8787/v1/models，"
                                     "名单里不一定都可用；被拒自动回退）")
        self.fl_model_label.setWordWrap(True)
        vf.addWidget(self.fl_model_label)
        self.fl_model_edit = QLineEdit(str(fl.get("model") or "space-bunny-free"))
        self.fl_model_edit.setStyleSheet(theme.input_box())
        self.fl_model_edit.setPlaceholderText("space-bunny-free")
        vf.addWidget(self.fl_model_edit)
        self.fl_fallback_label = QLabel("回退模型（白嫖模型被上游拒绝时自动改用）")
        vf.addWidget(self.fl_fallback_label)
        self.fl_fallback_edit = QLineEdit(str(fl.get("fallback_model") or "space-bunny-free"))
        self.fl_fallback_edit.setStyleSheet(theme.input_box())
        self.fl_fallback_edit.setPlaceholderText("space-bunny-free")
        vf.addWidget(self.fl_fallback_edit)
        v1.addWidget(self.fl_box)

        # 单次回复上限：两个通道共用，一直显示
        tok_row = QHBoxLayout()
        tok_row.addWidget(QLabel("单次回复上限"))
        self.tokens_spin = QSpinBox()
        self.tokens_spin.setRange(256, 32768)
        self.tokens_spin.setSingleStep(512)
        self.tokens_spin.setValue(int(cfg.get("max_tokens", 2048)))
        tok_row.addWidget(self.tokens_spin)
        tok_row.addStretch(1)
        v1.addLayout(tok_row)

        btn_row = QHBoxLayout()
        self.test_btn = QPushButton("测试连接")
        self.test_btn.setStyleSheet(theme.button())
        self.test_btn.clicked.connect(self._test)
        self.result_lab = QLabel("")
        self.result_lab.setStyleSheet(theme.label(theme.TEXT_MUTE, 12))
        btn_row.addWidget(self.test_btn)
        btn_row.addWidget(self.result_lab, 1)
        v1.addLayout(btn_row)
        v1.addStretch(1)

        # ---- 页 2：应用别名 ----
        alias_page = QWidget()
        v2 = QVBoxLayout(alias_page)
        v2.setSpacing(8)
        tip = QLabel("你对清言说左边的名字，她就打开右边的东西——教她认识你的应用。\n"
                     "「程序/网址」填 exe 完整路径、系统命令（notepad）或网址均可；"
                     "支持 %APPDATA% 这类环境变量；保存立即生效。\n"
                     "匹配不区分大小写和空格（说 chrome / Chrome 浏览器 都能认）。")
        tip.setWordWrap(True)
        tip.setStyleSheet(theme.label(theme.TEXT_MUTE, 12))
        v2.addWidget(tip)
        self.alias_table = QTableWidget(0, 2)
        self.alias_table.setHorizontalHeaderLabels(["我叫它", "程序 / 网址"])
        self.alias_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.alias_table.verticalHeader().setVisible(False)
        self.alias_table.setStyleSheet(theme.table())
        self.alias_table.setMinimumHeight(260)
        for alias, target in (cfg.get("app_aliases") or {}).items():
            self._append_alias_row(alias, target)
        if self.alias_table.rowCount() == 0:
            self._append_alias_row("", "")
        alias_btns = QHBoxLayout()
        add_btn = QPushButton("+ 加一行")
        add_btn.setStyleSheet(theme.button())
        add_btn.clicked.connect(lambda: self._append_alias_row("", ""))
        del_btn = QPushButton("删除选中行")
        del_btn.setStyleSheet(theme.button())
        del_btn.clicked.connect(self._delete_alias_rows)
        alias_btns.addWidget(add_btn)
        alias_btns.addWidget(del_btn)
        alias_btns.addStretch(1)
        v2.addWidget(self.alias_table)
        v2.addLayout(alias_btns)

        # ---- 页 3：个人资料 ----
        profile_page = QWidget()
        v3 = QVBoxLayout(profile_page)
        v3.setSpacing(8)
        v3.addWidget(QLabel("用户名（清言会这样称呼你，留空则显示「我」）"))
        self.name_edit = QLineEdit(cfg.get("user_name", ""))
        self.name_edit.setStyleSheet(theme.input_box())
        self.name_edit.setPlaceholderText("例如：主人、阿伦、Boss…")
        v3.addWidget(self.name_edit)

        v3.addWidget(QLabel("头像（选一张图片，自动裁成圆形；留空用默认「主」字头像）"))
        avatar_row = QHBoxLayout()
        self.avatar_preview = QLabel()
        self.avatar_preview.setFixedSize(64, 64)
        self._refresh_avatar_preview()
        pick_btn = QPushButton("选择图片…")
        pick_btn.setStyleSheet(theme.button())
        pick_btn.clicked.connect(self._pick_avatar)
        reset_btn = QPushButton("恢复默认")
        reset_btn.setStyleSheet(theme.button())
        reset_btn.clicked.connect(self._reset_avatar)
        avatar_row.addWidget(self.avatar_preview)
        avatar_row.addWidget(pick_btn)
        avatar_row.addWidget(reset_btn)
        avatar_row.addStretch(1)
        v3.addLayout(avatar_row)
        v3.addStretch(1)

        # ---- 组装：三个子页 + 底部按钮 ----
        # 桌宠全局设置（开机自启/喝水提醒）在独立的 PetSettingsDialog（pet_settings.py），
        # 这里只放聊天专项：接口 / 应用别名 / 个人资料。
        self.tabs = QTabWidget()
        self.tabs.addTab(api_page, "接口")
        self.tabs.addTab(alias_page, "应用别名")
        self.tabs.addTab(profile_page, "个人资料")
        root = QVBoxLayout(self)
        root.addWidget(self.tabs)

        ok = QPushButton("保存并关闭")
        ok.setStyleSheet(theme.button(primary=True))
        ok.clicked.connect(self._save)
        cancel = QPushButton("取消")
        cancel.setStyleSheet(theme.button())
        cancel.clicked.connect(self.reject)
        tail = QHBoxLayout()
        tail.addStretch(1)
        tail.addWidget(cancel)
        tail.addWidget(ok)
        root.addLayout(tail)

        self.test_done.connect(self._on_test_done)
        from .glm_client import GlmClient
        self._test_client = GlmClient(self.cfg, self)
        self._test_client.finished.connect(lambda _text, _usage: self._on_test_done(True, "连接及回复正常"))
        self._test_client.failed.connect(lambda msg: self._on_test_done(False, msg))
        self._test_client.tool_calls_finished.connect(lambda _calls: self._on_test_done(False, "连接测试意外返回工具请求"))

        # 通道初始状态（全部控件就绪后设置并同步一次）
        self.chan_freelane.setChecked(fl_enabled)
        self.chan_freelane.toggled.connect(self._sync_channel)
        self._sync_channel()

    # ---------- 模型通道 联动 ----------

    def _sync_channel(self):
        use_fl = self.chan_freelane.isChecked()
        # 只显示当前通道对应的那组选项，另一组整体隐藏
        self.custom_box.setVisible(not use_fl)
        self.fl_box.setVisible(use_fl)
        if use_fl:
            self.chan_hint.setText(
                "白嫖通道：桌宠内置代理（本机 127.0.0.1）转发到上游免费模型——免费、免 Key、"
                "不需要网络代理。被上游拒绝的模型会自动回退到「回退模型」。"
                "⚠️ 聊天内容会明文发往上游，免费模型可能用于训练。")
        else:
            fl = self.cfg.get("freelane") or {}
            if fl.get("enabled"):
                snap = fl.get("custom") or {}
                self.effort_combo.setCurrentText(str(snap.get("thinking_effort") or "low"))
            self.chan_hint.setText(
                "自定义 API：任何 OpenAI 兼容服务（GLM / DeepSeek / 中转站等）。"
                "切到白嫖通道时这里的配置会记住，切回自动还原。")

    def _freelane_port(self) -> int:
        """白嫖通道实际端口：优先问本进程内嵌代理的真实端口（被占端口时会动态换），
        其次读当前生效的 api_base，最后才用配置端口。"""
        try:
            from freelane.freelane import running_port
            live = running_port()
            if live:
                return live
        except Exception:
            pass
        m = re.match(r"http://127\.0\.0\.1:(\d+)/v1/?$",
                     str(self.cfg.get("api_base") or "").strip())
        if m:
            return int(m.group(1))
        fl = self.cfg.get("freelane") or {}
        return int(fl.get("port") or 8787)

    # ---------- 应用别名 ----------

    def _append_alias_row(self, alias: str, target: str):
        r = self.alias_table.rowCount()
        self.alias_table.insertRow(r)
        self.alias_table.setItem(r, 0, QTableWidgetItem(alias))
        self.alias_table.setItem(r, 1, QTableWidgetItem(target))
        # 行多时新行在可视区外会"看不见"——自动滚到新行并进入编辑
        self.alias_table.scrollToBottom()
        self.alias_table.setCurrentCell(r, 0)
        self.alias_table.editItem(self.alias_table.item(r, 0))

    def _delete_alias_rows(self):
        rows = sorted({i.row() for i in self.alias_table.selectedIndexes()}, reverse=True)
        if not rows:  # 没选中就删最后一行（若只有一行则清空）
            rows = [self.alias_table.rowCount() - 1] if self.alias_table.rowCount() else []
        for r in rows:
            self.alias_table.removeRow(r)

    def _collect_aliases(self) -> dict:
        out = {}
        for r in range(self.alias_table.rowCount()):
            alias = (self.alias_table.item(r, 0).text().strip()
                     if self.alias_table.item(r, 0) else "")
            target = (self.alias_table.item(r, 1).text().strip()
                      if self.alias_table.item(r, 1) else "")
            if alias and target:
                out[alias] = target
        return out

    # ---------- 个人资料 ----------

    def _refresh_avatar_preview(self):
        from PySide6.QtGui import QPixmap
        if self._pending_avatar is not None:
            from PIL.ImageQt import ImageQt
            pm = QPixmap.fromImage(ImageQt(self._pending_avatar))
        else:
            custom = os.path.join(DATA_DIR, "user_avatar.png")
            pm = QPixmap(custom if not self._avatar_reset and os.path.exists(custom)
                         else os.path.join(ASSETS_DIR, "chat_avatar_user.png"))
        self.avatar_preview.setPixmap(pm.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _pick_avatar(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "选择头像图片", "",
                                              "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        from PIL import Image, ImageDraw
        try:
            img = Image.open(path).convert("RGBA")
        except Exception as e:
            self.result_lab.setText(f"⚠️ 图片读取失败：{e}")
            return
        side = min(img.size)
        img = img.crop(((img.width - side) // 2, (img.height - side) // 2,
                        (img.width + side) // 2, (img.height + side) // 2))
        size = 160
        img = img.resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(img, (0, 0), mask.resize((size, size), Image.LANCZOS))
        self._pending_avatar = out
        self._avatar_reset = False
        self._refresh_avatar_preview()

    def _reset_avatar(self):
        self._avatar_reset = True
        self._pending_avatar = None
        self._refresh_avatar_preview()

    # ---------- 保存 ----------

    def _values(self):
        return {
            "api_key": self.key_edit.text().strip(),
            "api_base": self.base_edit.text().strip().rstrip("/") or
                        "https://open.bigmodel.cn/api/paas/v4",
            "model": self.model_combo.currentText().strip(),
            "thinking_effort": self.effort_combo.currentText(),
            "max_tokens": self.tokens_spin.value(),
        }

    def _confirm_freelane_privacy(self) -> bool:
        """每次从自定义 API 切到白嫖通道时确认一次：聊天内容会明文发往第三方上游。"""
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("启用白嫖通道")
        box.setText("启用后，你的聊天内容会明文发送到第三方免费模型上游，"
                    "对方可能记录并用于训练。\n\n请不要在对话中输入密码、密钥或其他敏感信息。\n是否继续？")
        ok = box.addButton("我已了解，启用", QMessageBox.AcceptRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        return box.clickedButton() is ok

    def _save(self):
        if not self.chan_freelane.isChecked():
            v = self._values()
            try:
                parsed = urlsplit(v["api_base"])
                if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError("API 地址必须是有效 http/https 地址且不能包含账号密码")
                parsed.port
                if not v["model"] or not v["api_key"]:
                    raise ValueError("模型名和 API Key 不能为空")
            except ValueError as e:
                self.result_lab.setText(str(e))
                return
        fl = dict(self.cfg.get("freelane") or {})
        old_enabled = bool(fl.get("enabled"))
        if self.chan_freelane.isChecked():
            fl_model = self.fl_model_edit.text().strip() or "space-bunny-free"
            # 回退留空：用代理默认回退模型（以前默认 = 主模型，回退永远不会发生）
            fl_fallback = self.fl_fallback_edit.text().strip() or _FL_DEFAULT_FALLBACK
            if not old_enabled and not self._confirm_freelane_privacy():
                return   # 用户没同意就不切换、不保存任何内容
            if not old_enabled:
                # 首次切到白嫖：把当前自定义 API 配置快照下来，供切回时还原
                fl["custom"] = {"api_base": self.cfg.get("api_base", ""),
                                "api_key": self.cfg.get("api_key", ""),
                                "chat_model": self.cfg.get("chat_model", ""),
                                "thinking_effort": self.cfg.get("thinking_effort", "low")}
            fl["enabled"] = True
            fl["model"] = fl_model
            fl["fallback_model"] = fl_fallback
            self.cfg["freelane"] = fl
            self.cfg["api_base"] = f"http://127.0.0.1:{self._freelane_port()}/v1"
            self.cfg["api_key"] = "freelane"
            self.cfg["chat_model"] = fl_model
            self.cfg["thinking_effort"] = "off"
            # 免费模型由 freelane.model 管理，不混入自定义模型列表。
        else:
            v = self._values()
            parsed = urlsplit(v["api_base"])
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                self.result_lab.setText("API 地址必须是有效 http/https 地址")
                return
            if not v["model"]:
                self.result_lab.setText("⚠️ 模型名不能为空")
                return
            fl["enabled"] = False
            self.cfg["freelane"] = fl
            self.cfg["api_key"] = v["api_key"]
            self.cfg["api_base"] = v["api_base"]
            self.cfg["chat_model"] = v["model"]
            self.cfg["thinking_effort"] = self.effort_combo.currentText()
            if v["model"] not in self.cfg.get("chat_models", []):
                self.cfg["chat_models"] = list(self.cfg.get("chat_models", [])) + [v["model"]]
        self.cfg["max_tokens"] = self.tokens_spin.value()
        self.cfg["app_aliases"] = self._collect_aliases()
        self.cfg["user_name"] = self.name_edit.text().strip()
        target_avatar = os.path.join(DATA_DIR, "user_avatar.png")
        old_avatar = None
        avatar_changed = self._avatar_reset or self._pending_avatar is not None
        try:
            if avatar_changed and os.path.exists(target_avatar):
                with open(target_avatar, "rb") as f:
                    old_avatar = f.read()
            if self._avatar_reset and os.path.exists(target_avatar):
                os.remove(target_avatar)
            elif self._pending_avatar is not None:
                os.makedirs(DATA_DIR, exist_ok=True)
                tmp = target_avatar + ".tmp"
                self._pending_avatar.save(tmp, format="PNG")
                os.replace(tmp, target_avatar)
            if hasattr(self._live_cfg, "commit"):
                self._live_cfg.commit(self.cfg)
            else:
                previous = copy.deepcopy(dict(self._live_cfg))
                try:
                    self._live_cfg.update(self.cfg)
                    self._live_cfg.save()
                except Exception:
                    self._live_cfg.clear()
                    self._live_cfg.update(previous)
                    raise
        except Exception as e:
            if avatar_changed:
                try:
                    if old_avatar is not None:
                        with open(target_avatar + ".rollback", "wb") as f:
                            f.write(old_avatar)
                        os.replace(target_avatar + ".rollback", target_avatar)
                    elif os.path.exists(target_avatar):
                        os.remove(target_avatar)
                except OSError as rollback_error:
                    self.result_lab.setText(f"保存失败且头像恢复失败：{rollback_error}")
                    return
            self.result_lab.setText(f"保存失败：{e}")
            return
        runtime_refresh = getattr(self.parent(), "runtime_config_refresh", None)
        if runtime_refresh:
            runtime_refresh()
        self._test_client.cancel(silent=True)
        self.accept()

    def reject(self):
        self._pending_avatar = None
        self._test_client.cancel(silent=True)
        super().reject()

    # ---------- 测试连接 ----------

    def _test(self):
        if self.chan_freelane.isChecked():
            # 白嫖通道：测本机代理（免 Key）；模型用白嫖模型字段
            v = {"api_base": f"http://127.0.0.1:{self._freelane_port()}/v1",
                 "api_key": "freelane",
                 "model": self.fl_model_edit.text().strip() or "space-bunny-free",
                 "thinking_effort": "off"}
        else:
            v = self._values()
            if not v["api_key"]:
                self.result_lab.setText("⚠️ 请先填 API Key")
                return
            try:
                parsed = urlsplit(v["api_base"])
                parsed.port
                if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError("API 地址必须是有效 http/https 地址")
            except ValueError as e:
                self.result_lab.setText(str(e))
                return
        self.test_btn.setEnabled(False)
        self.result_lab.setText("测试中…")
        config = dict(v, chat_model=v["model"], max_tokens=2048)
        self._test_client.send([{"role": "user", "content": "hi"}], v["model"], stream=False, config=config)

    def _on_test_done(self, ok: bool, msg: str):
        self.test_btn.setEnabled(True)
        self.result_lab.setText(("✅ " if ok else "❌ ") + msg)
