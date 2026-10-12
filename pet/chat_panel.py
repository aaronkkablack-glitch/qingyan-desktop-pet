"""聊天面板：流式对话 + 日程上下文注入 + 模型切换。

对话上下文只保留最近 N 条（config.max_history_messages）；
系统提示词每轮重建（注入当前时间与今日日程）。
"""
import datetime as dt
import copy
import html
import json as _json
import os
import threading
import urllib.error
import urllib.request

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QKeySequence, QFont, QFontMetrics, QShortcut
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QPlainTextEdit, QPushButton,
                               QLabel, QTextBrowser, QVBoxLayout, QWidget)

from .config import ASSETS_DIR, DATA_DIR, DEFAULT_PERSONA, backup_corrupt
from . import theme
from . import usage_reader
from .tools import ToolHost, tool_schemas
from .net import DIRECT_OPENER

AVATAR_PET = QUrl.fromLocalFile(os.path.join(ASSETS_DIR, "chat_avatar_pet.png")).toString()
AVATAR_USER_DEFAULT = QUrl.fromLocalFile(os.path.join(ASSETS_DIR, "chat_avatar_user.png")).toString()
HISTORY_PATH = os.path.join(DATA_DIR, "chat_history.json")
HISTORY_KEEP = 400   # 持久化保留最近 N 条（防文件无限膨胀）
MAX_TOOL_ROUNDS = 3  # 一次提问最多执行几轮工具


def avatar_user() -> str:
    """用户头像：data/user_avatar.png（设置页上传）优先，默认蓝「主」字兜底。"""
    custom = os.path.join(DATA_DIR, "user_avatar.png")
    if os.path.exists(custom):
        return QUrl.fromLocalFile(custom).toString()
    return AVATAR_USER_DEFAULT


def _now() -> str:
    return dt.datetime.now().strftime("%H:%M")


def _now_full() -> str:
    """返回给上下文使用的本地完整时间，避免模型无法判断消息间隔。"""
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def build_css() -> str:
    return f"""
    QWidget {{ background: {theme.BG}; color: {theme.TEXT_DIM};
              font-family: 'Microsoft YaHei UI', 'Segoe UI'; }}
    QTextBrowser {{ background: {theme.CARD}; border: 1px solid {theme.TRACK};
                   border-radius: 12px; padding: 8px; {theme.scrollbar()} }}
    QPlainTextEdit {{ {theme.input_box(multiline=True)} }}
    QComboBox {{ {theme.combo()} }}
    QLabel#status {{ {theme.label(theme.TEXT_MUTE, 12)} }}
    QLabel#modelLab {{ {theme.label(theme.TEXT_MUTE, 12)} }}
    """


def build_system_prompt(cfg, store, extra: str = "") -> str:
    now = dt.datetime.now()
    persona = cfg.get("system_prompt") or DEFAULT_PERSONA
    wd = "一二三四五六日"[now.weekday()]
    name = (cfg.get("user_name") or "").strip()
    named = f"\n主人喜欢被称作：{name}。" if name else ""
    return (f"{persona}{named}\n"
            f"当前真实时间：{now:%Y-%m-%d %H:%M:%S}（周{wd}，本机时间）。\n"
            "时间规则：上面的当前真实时间是唯一有效的现在；历史消息里的旧时间、旧回答和旧日程都不能当作当前状态。"
            "用户询问现在、多久了、还要多久或相对时间时，必须以当前真实时间重新计算；不确定时不要沿用上一轮回答。\n"
            f"今日日程：{store.summary_for(now)}"
            + (f"\n{extra}" if extra else ""))


class ChatPanel(QWidget):
    tool_round_done = Signal(str, list, object)   # (正文或"", tool_calls, usage)
    tool_round_error = Signal(str)
    # 一次提问（含全部工具轮）的唯一结束出口："done" / "error"——桌宠动作据此收尾
    turn_ended = Signal(str)

    def __init__(self, cfg, glm, store, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.glm = glm
        self.store = store
        self.history: list[dict] = []     # [{role, content}]，不含 system
        self._stream_buf = ""
        self._last_html = None            # 上次渲染的 HTML（脏检查，未变不重建文档）
        self._history_no_save = False
        self.setWindowTitle("和清言聊天")
        self.resize(560, 640)
        self.setStyleSheet(build_css())

        top = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.addItems(cfg["chat_models"])
        self.model_combo.setCurrentText(cfg["chat_model"])
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        model_lab = QLabel("模型：")
        model_lab.setObjectName("modelLab")
        top.addWidget(model_lab)
        top.addWidget(self.model_combo)
        self.settings_btn = QPushButton("⚙ 设置")
        self.settings_btn.setStyleSheet(theme.button())
        self.settings_btn.setToolTip("配置 API Key / 服务商 / 模型 / 应用别名 / 个人资料")
        self.settings_btn.clicked.connect(self._open_settings)
        top.addWidget(self.settings_btn)
        self.clear_btn = QPushButton("🗑")
        self.clear_btn.setStyleSheet(theme.button())
        self.clear_btn.setToolTip("清空聊天记录")
        self.clear_btn.clicked.connect(self._confirm_clear)
        top.addWidget(self.clear_btn)
        top.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("status")
        top.addWidget(self.status)

        self.browser = QTextBrowser()
        self.browser.setFont(QFont("Microsoft YaHei UI", 10))
        self.browser.setOpenExternalLinks(True)

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("回车发送，Shift+回车换行")
        self.input.setFixedHeight(64)
        self.input.installEventFilter(self)
        self.send_btn = QPushButton("发送")
        self.send_btn.setStyleSheet(theme.button(primary=True))
        self.send_btn.clicked.connect(self.send)
        self.stop_btn = QPushButton("停止回复")
        self.stop_btn.setStyleSheet(theme.button())
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_reply)

        bottom = QHBoxLayout()
        bottom.addWidget(self.input, 1)
        bottom.addWidget(self.send_btn, 0, Qt.AlignBottom)
        bottom.addWidget(self.stop_btn, 0, Qt.AlignBottom)

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(self.browser, 1)
        root.addLayout(bottom)

        self.toolhost = ToolHost(cfg, self)
        self.toolhost.set_confirm(self._confirm_tool)
        self._water_provider = None      # main 注入：返回喝水提醒上下文文案
        self._activity_hook = None       # main 注入：聊天活动时通知（顺延桌宠睡觉倒计时）
        self._load_history()
        self.glm.tool_calls_finished.connect(self._on_tool_calls)
        self.tool_round_done.connect(self._on_tool_round_done)
        self.tool_round_error.connect(self._on_tool_round_error)
        self._tool_rounds = 0
        self._busy = False         # 会话级忙碌：覆盖流式请求 + 工具执行 + 工具回传线程
        self._req_model = ""       # 发起请求时的模型（记账用，避免中途切模型记错）
        self._request_config = None
        self._closing = False

        # 只在请求进行中跑（send 时 start，_end_turn 时 stop）
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(80)
        self._render_timer.timeout.connect(self._render)

        self.glm.thinking_started.connect(lambda: self.status.setText("💭 清言思考中…"))
        self.glm.chunk.connect(self._on_chunk)
        self.glm.finished.connect(self._on_finished)
        self.glm.failed.connect(self._on_failed)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self.send)
        self._render()
        if getattr(cfg, "credential_error", ""):
            self.status.setText(cfg.credential_error)

    # ---------- 发送 ----------

    def set_water_provider(self, fn):
        """fn() -> str|None：喝水提醒上下文（如"每20分钟一次，下次 14:30"），注入 system prompt。"""
        self._water_provider = fn

    def set_activity_hook(self, fn):
        """fn()：聊天活动时调用（打字/发送/收到流式内容）——桌宠睡觉倒计时顺延用。"""
        self._activity_hook = fn

    def _activity(self):
        if self._activity_hook:
            try:
                self._activity_hook()
            except Exception:
                pass

    def _extra_context(self) -> str:
        try:
            return (self._water_provider() or "") if self._water_provider else ""
        except Exception:
            return ""

    def _persist_history(self):
        """聊天记录落盘：只存普通 user/assistant 消息（tool 链不存），保留最近 HISTORY_KEEP 条。"""
        self._trim_history()
        if self._history_no_save:
            self.status.setText("聊天记录无法安全备份，已禁止覆盖原文件")
            return
        plain = [m for m in self.history
                 if m["role"] in ("user", "assistant") and not m.get("tool_calls")]
        try:
            os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
            tmp_path = HISTORY_PATH + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                _json.dump(plain[-HISTORY_KEEP:], f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, HISTORY_PATH)
        except OSError as e:
            self.status.setText(f"聊天记录保存失败：{e}")

    def _trim_history(self):
        if len(self.history) <= HISTORY_KEEP:
            return
        start = len(self.history) - HISTORY_KEEP
        # 从一个用户轮次的起点裁剪，不留下孤立 tool 或半截工具链。
        boundaries = [i for i, m in enumerate(self.history) if m["role"] == "user"]
        if getattr(self, "_busy", False):
            boundaries = boundaries[:-1]
        eligible = [i for i in boundaries if i >= start]
        if eligible:
            self.history = self.history[eligible[0]:]
        elif not getattr(self, "_busy", False):
            # 单轮异常长的工具链结束后，只保留普通消息，不保留半截协议链。
            plain = [m for m in self.history if m["role"] != "tool" and not m.get("tool_calls")]
            self.history = plain[-HISTORY_KEEP:]

    def _load_history(self):
        if not os.path.exists(HISTORY_PATH):
            return
        try:
            with open(HISTORY_PATH, encoding="utf-8") as f:
                msgs = _json.load(f)
            if not isinstance(msgs, list) or any(not isinstance(m, dict) for m in msgs):
                raise ValueError("聊天记录必须是消息列表")
            self.history = [m for m in msgs if m.get("role") in ("user", "assistant")
                            and isinstance(m.get("content"), str)]
        except OSError as e:
            self._history_no_save = True
            self.status.setText(f"聊天记录读取失败：{e}")
            self.history = []
        except (ValueError, TypeError) as e:
            self._history_no_save = backup_corrupt(HISTORY_PATH) is None
            self.status.setText(f"聊天记录损坏：{e}")
            self.history = []

    def clear_history(self):
        if self.busy:
            self.status.setText("请先停止回复，再清空记录")
            return
        self.history = []
        self._stream_buf = ""
        try:
            os.remove(HISTORY_PATH)
        except OSError:
            pass
        self._render(force=True)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.input and ev.type() == QEvent.KeyPress:
            self._activity()          # 打字即活动：聊天期间不让清言睡着
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and not ev.modifiers() & Qt.ShiftModifier:
                self.send()
                return True
        return super().eventFilter(obj, ev)

    def _on_model_changed(self, model):
        self.cfg["chat_model"] = model
        self.cfg.save()

    def _open_settings(self):
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            # 保存后同步模型下拉（新模型已追加进 chat_models）
            self.model_combo.blockSignals(True)
            self.model_combo.clear()
            self.model_combo.addItems(self.cfg.get("chat_models", []))
            self.model_combo.setCurrentText(self.cfg.get("chat_model", ""))
            self.model_combo.blockSignals(False)
            self.status.setText("⚙ 设置已保存，立即生效")
            self._render(force=True)  # 头像/用户名可能已换

    def _confirm_tool(self, title: str, text: str) -> bool:
        """模型要执行敏感操作（开机自启 / 非别名程序）前让用户点头；默认按钮是「拒绝」。"""
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(title)
        box.setText(text)
        allow = box.addButton("允许", QMessageBox.AcceptRole)
        deny = box.addButton("拒绝", QMessageBox.RejectRole)
        box.setDefaultButton(deny)
        box.setEscapeButton(deny)
        box.exec()
        return box.clickedButton() is allow

    def _confirm_clear(self):
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self, "清空聊天记录",
                                "确定清空和清言的全部聊天记录吗？（不可恢复）",
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) == QMessageBox.Yes:
            self.clear_history()
            self.status.setText("聊天记录已清空")

    @property
    def busy(self) -> bool:
        return self._busy or getattr(self.glm, "busy", False)

    def send(self):
        if self.busy:  # 回车 / Ctrl+Enter 不经过按钮，这里是唯一闸门
            self.status.setText("清言还在回复上一条…")
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        if not self.cfg.get("api_key"):
            self._sys_line("⚠️ 还没有配置 API Key：点右上「⚙ 设置」填写并保存即可")
            return
        self._activity()
        self.input.clear()
        self.history.append({"role": "user", "content": text,
                             "_t": _now(), "_ts": _now_full()})
        self._persist_history()
        self._stream_buf = ""
        self._busy = True
        self._tool_rounds = 0
        self._req_model = self.cfg["chat_model"]
        self._request_config = copy.deepcopy(self.cfg.d if hasattr(self.cfg, "d") else dict(self.cfg))
        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._render_timer.start()
        self._request()

    def _end_turn(self, outcome: str, status: str = ""):
        """一次提问的统一收尾（普通完成 / 工具完成 / 工具超限 / 任何失败都走这里）。"""
        self._busy = False
        self._trim_history()
        self._tool_rounds = 0
        self._stream_buf = ""
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._render_timer.stop()
        if status:
            self.status.setText(status)
        self._render()
        self.turn_ended.emit(outcome)

    def stop_reply(self):
        if not self.busy:
            return
        partial = self._stream_buf
        self.glm.cancel(silent=True)
        if partial:
            self._sys_line(partial + "\n（已停止，回复不完整）")
        self._end_turn("cancelled", "已停止回复")

    def shutdown(self):
        self._closing = True
        self.glm.cancel(silent=True)
        self._render_timer.stop()

    def _usage_status(self, usage) -> str:
        if isinstance(usage, dict) and usage:
            try:
                usage_reader.record_pet_usage(self._req_model or self.cfg["chat_model"], usage)
            except (OSError, ValueError, TypeError) as e:
                return f"回复完成，用量记账失败：{e}"
            return (f"本次 {usage.get('total_tokens', '?')} tokens"
                    f"（输入 {usage.get('prompt_tokens', '?')} / 输出 {usage.get('completion_tokens', '?')}）")
        return "完成"

    @staticmethod
    def _strip_meta(m: dict) -> dict:
        """history 消息转 API 格式：给普通消息附带发生时间，剔除本地展示字段。"""
        out = {"role": m["role"], "content": m.get("content") or ""}
        if m["role"] in ("user", "assistant") and not m.get("tool_calls"):
            stamp = m.get("_ts") or m.get("_t")
            if stamp:
                out["content"] = f"[这条消息发送于 {stamp}]\n{out['content']}"
        if m.get("tool_calls"):
            out["tool_calls"] = m["tool_calls"]
        if m["role"] == "tool":
            out["tool_call_id"] = m.get("tool_call_id", "")
        return out

    def _context_messages(self) -> list[dict]:
        """system + 最近 N 条上下文。

        - 本地提示（_local）不发给模型；
        - 当前这轮（最近一条 user 起的 user→assistant(tool_calls)→tool… 链）永远完整保留，
          哪怕超过窗口——拆开会违反 tool 必须紧跟对应 assistant 的协议，或丢掉用户的问题；
        - 窗口起点不落在 tool / 带 tool_calls 的 assistant 上。
        """
        msgs = [m for m in self.history if not m.get("_local")]
        cfg = self._request_config or self.cfg
        window = max(1, int(cfg.get("max_history_messages", 20)))
        last_user = max((i for i, m in enumerate(msgs) if m["role"] == "user"), default=len(msgs))
        start = min(max(0, len(msgs) - window), last_user)
        tail = msgs[start:]
        while tail and (tail[0].get("role") == "tool" or tail[0].get("tool_calls")):
            tail.pop(0)
        return ([{"role": "system", "content": build_system_prompt(
                    cfg, self.store, self._extra_context())}]
                + [self._strip_meta(m) for m in tail])

    def _request(self):
        """首轮流式请求（自动携带工具定义）；工具结果回传走 _continue_nonstream。"""
        messages = self._context_messages()
        self.status.setText("💭 清言思考中…")
        self.send_btn.setEnabled(False)
        self._render()
        kwargs = {"config": self._request_config} if self._request_config else {}
        self.glm.send(messages, self._req_model or self.cfg["chat_model"],
                      tools=tool_schemas(self._request_config or self.cfg), stream=True, **kwargs)

    # ---------- 工具调用（agent 循环） ----------

    def _on_tool_calls(self, calls):
        if self._closing:
            return
        self._handle_tool_calls(calls, self.glm._full or "")

    def _handle_tool_calls(self, calls, assistant_content=""):
        """模型要求调用工具：执行 → 结果回传（独立线程非流式请求，彻底隔离 Qt 网络栈）。"""
        # history 里补 assistant(tool_calls) 消息，保证上下文合法
        # 超限判断放在执行之前：第 MAX+1 轮的工具不应再被执行
        self._tool_rounds += 1
        if self._tool_rounds > MAX_TOOL_ROUNDS:
            self._sys_line("（工具调用轮次过多，已停止）")
            self._end_turn("error", "⚠️ 工具调用轮次过多，已停止")
            return
        for i, tc in enumerate(calls):   # 缺 id 的补一个，保证 tool 消息能配对
            if not tc.get("id"):
                tc["id"] = f"call_{self._tool_rounds}_{i}"
        self.history.append({"role": "assistant", "content": assistant_content,
                             "tool_calls": calls, "_t": _now(), "_ts": _now_full()})
        for tc in calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            raw_args = fn.get("arguments")
            try:
                args = raw_args if isinstance(raw_args, dict) else _json.loads(raw_args or "{}")
            except Exception:
                args = {}
            self.status.setText(f"🔧 执行工具：{name}")
            try:
                ok, result = self.toolhost.run(name, args)
            except Exception as e:  # 单个工具炸了不能打断整轮循环
                ok, result = False, f"工具执行异常：{e}"
            self.status.setText(f"🔧 {result}")
            # 工具结果作为 tool 消息回传
            self.history.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                 "content": result, "_t": _now(), "_ts": _now_full()})
        self._continue_nonstream()

    def _continue_nonstream(self):
        """延后一拍用同一 Qt 客户端发送非流式结果，可取消且不嵌套 reply 回调栈。"""
        messages = self._context_messages()
        model = self._req_model or self.cfg["chat_model"]
        self.status.setText("💭 清言思考中…")
        cfg = copy.deepcopy(self._request_config or (self.cfg.d if hasattr(self.cfg, "d") else dict(self.cfg)))
        # 快照对象身份充当轮次令牌：停止后/新轮开始后，旧发送任务自动失效。
        token = self._request_config
        def dispatch():
            if self._closing or not self._busy or token is not self._request_config:
                return
            self.glm.send(messages, model, tools=tool_schemas(cfg), stream=False, config=cfg)
        QTimer.singleShot(0, dispatch)

    def _on_tool_round_done(self, text, calls, usage):
        if getattr(self, "_closing", False):
            return
        if calls:
            # 模型继续要求工具（罕见）：按 tool_calls 继续循环
            self._handle_tool_calls(calls, text)
            return
        if not text:
            self._sys_line("⚠️ 工具执行完了，但模型没有给出回复")
            self._end_turn("error", "❌ 空回复")
            return
        self.history.append({"role": "assistant", "content": text,
                             "_t": _now(), "_ts": _now_full()})
        self._persist_history()
        self._end_turn("done", self._usage_status(usage))

    def _on_tool_round_error(self, msg):
        if getattr(self, "_closing", False):
            return
        self._sys_line(f"⚠️ {msg}")
        self._end_turn("error", f"❌ {msg}")

    # ---------- 流式接收 ----------

    def _on_chunk(self, text):
        if self._closing:
            return
        # 长历史的Qt文档全量重排成本高于80ms，避免连续占用UI线程。
        self._render_timer.setInterval(400 if len(self.history) > 200 else 160 if len(self.history) > 80 else 80)
        self._activity()          # 清言正在回话也是活动
        self._stream_buf += text

    def _on_finished(self, full_text, usage):
        if self._closing:
            return
        self.history.append({"role": "assistant", "content": full_text,
                             "_t": _now(), "_ts": _now_full()})
        self._persist_history()
        self._end_turn("done", self._usage_status(usage))

    def _on_failed(self, msg):
        if getattr(self, "_closing", False):
            return
        partial = getattr(self.glm, "interrupted_text", "") or ""
        if partial:
            # 半截回复保留给用户看，但标成本地提示：不进模型上下文、不算完整回答
            self._sys_line(f"{partial}\n（连接中断，回复不完整）")
        self._end_turn("error", f"❌ {msg}")

    def _sys_line(self, text):
        """本地提示：展示给用户、会落盘，但带 _local 标记，不发给模型（_context_messages 过滤）。"""
        self.history.append({"role": "assistant", "content": text, "_local": True,
                             "_t": _now(), "_ts": _now_full()})
        self._persist_history()
        self._render()

    # ---------- 渲染 ----------

    def _assistant_message_html(self, text: str, stamp: str) -> str:
        metrics = QFontMetrics(self.browser.font())
        text_width = max((metrics.horizontalAdvance(line) for line in text.split("\n")), default=0)
        total_width = max(160, self.browser.viewport().width() - 32)
        max_width = max(56, int((total_width - 56) * 0.75))
        bubble_width = min(max_width, max(40, text_width + 16))
        spacer_width = max(1, total_width - bubble_width - 56)
        body = html.escape(text).replace("\n", "<br>")
        return (
            f"<table cellspacing='0' cellpadding='0' width='{total_width}'>"
            "<tr><td width='56'></td><td colspan='2' align='left'>"
            f"<div class='who'>清言 · {html.escape(stamp)}</div></td></tr><tr>"
            f"<td valign='top' width='56' height='48' align='left'><img src='{AVATAR_PET}' width='40' height='40'></td>"
            f"<td width='{bubble_width}' valign='top'>"
            f"<table width='{bubble_width}' cellspacing='0' cellpadding='8' bgcolor='{theme.BUBBLE_ASSISTANT_BG}'>"
            f"<tr><td align='left'><div style='color:{theme.TEXT};'>{body}</div></td></tr></table></td>"
            f"<td width='{spacer_width}'></td>"
            "</tr><tr><td colspan='3' height='12'></td></tr></table>"
        )

    def _build_html(self) -> str:
        parts = ["<style>",
                 ".u{background:rgba(79,124,255,0.16);color:#e8ecff;border-radius:12px;"
                  "padding:8px 12px;margin:2px 10px 4px 0;}",
                 ".a{background:" + theme.BUBBLE_ASSISTANT_BG + ";color:" + theme.TEXT
                 + ";border-radius:12px;padding:8px 12px;margin:2px 0 4px 10px;}",
                 ".who{color:" + theme.TEXT_MUTE + ";font-size:8pt;}",
                 "</style>"]
        if not self.history and not self._stream_buf:
            parts.append("<p style='color:" + theme.TEXT_MUTE + "'>和清言说点什么吧～双击桌宠也能打开这里。</p>")
        uname = html.escape((self.cfg.get("user_name") or "我").strip() or "我")
        user_avatar = avatar_user()   # 每次构建只查一次文件，不是每条消息一次
        for m in self.history:
            if m["role"] == "tool" or (m.get("tool_calls") and not m.get("content")):
                continue  # 工具链中间消息不展示
            body = html.escape(m.get("content") or "").replace("\n", "<br>")
            if m["role"] == "user":
                # Qt 富文本不支持浏览器的 shrink-to-fit，显式分配留白和气泡列。
                metrics = QFontMetrics(self.browser.font())
                text_width = max((metrics.horizontalAdvance(line)
                                  for line in (m.get("content") or "").split("\n")), default=0)
                total_width = max(160, self.browser.viewport().width() - 32)
                max_width = max(56, int((total_width - 56) * 0.75))
                bubble_width = min(max_width, max(40, text_width + 16))
                spacer_width = max(1, total_width - bubble_width - 56)
                # 用户侧整体向右移 12px：增加左侧留白，保持气泡宽度与头像间距。
                total_width += 12
                spacer_width += 12
                parts.append(
                     f"<table cellspacing='0' cellpadding='0' width='{total_width}'>"
                     "<tr><td colspan='2' align='right' style='padding-top:6px;'>"
                     f"<div class='who'>{uname} · {m.get('_t', '')}</div>"
                     "</td>"
                     f"<td rowspan='2' valign='top' width='56' height='48' align='right' style='padding-top:14px;'><img src='{user_avatar}' width='40' height='40'></td>"
                     "</tr><tr>"
                     f"<td width='{spacer_width}'></td>"
                     f"<td width='{bubble_width}' valign='top'>"
                     f"<table width='{bubble_width}' cellspacing='0' cellpadding='8' bgcolor='#202c48'>"
                     f"<tr><td align='left'><div style='color:#e8ecff;'>{body}</div></td></tr></table></td>"
                     "</tr><tr><td colspan='3' height='12'></td></tr></table>")
            else:
                parts.append(self._assistant_message_html(m.get("content") or "", m.get("_t", "")))
        if self._stream_buf:
            parts.append(self._assistant_message_html(self._stream_buf + "▍", _now()))
        return "".join(parts)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "browser"):
            # 拖动窗口边缘每秒会来几十个 resize：合并成停手后 60ms 内只重排一次
            t = getattr(self, "_resize_timer", None)
            if t is None:
                t = self._resize_timer = QTimer(self)
                t.setSingleShot(True)
                t.timeout.connect(lambda: self._render(force=True))
            t.start(60)

    def _render(self, force: bool = False):
        # 内容没变就绝不 setHtml：渲染定时器每 80ms 都会调这里，而 setHtml
        # 重建文档会把滚动条重置回顶端——空闲时用户往下拖会被不断吸回去。
        signature = (self.browser.viewport().width(), self.cfg.get("user_name"), self._stream_buf,
                     tuple((m.get("role"), m.get("content"), m.get("_t"), bool(m.get("tool_calls")))
                           for m in self.history))
        if not force and signature == getattr(self, "_render_signature", None):
            return
        html_str = self._build_html()
        self._render_signature = signature
        if not force and html_str == self._last_html:
            return
        sb = self.browser.verticalScrollBar()
        was_bottom = sb.value() >= sb.maximum() - 48
        pos = sb.value()
        self._last_html = html_str
        self.browser.setHtml(html_str)
        sb.setValue(sb.maximum() if was_bottom else pos)
