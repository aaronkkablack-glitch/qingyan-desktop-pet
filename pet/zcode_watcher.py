# -*- coding: utf-8 -*-
"""zcode 工作状态监控：解析 zcode 的 jsonl 事件流，按对话轮次(turn)驱动桌宠状态。

事件语义（2026-10-04 实测日志验证：所有 model.request 均带 turnId 且在 turn 边界内）：
  turn.started    一轮对话开始（用户消息 → agent 开始干活）
  turn.completed  一轮对话完成（agent 循环全部结束）
  turn.failed     一轮对话失败
其余事件（工具调用 / 心跳 memory_sample / 模型请求细节 / 网络重试）不影响状态：
思考动画覆盖整个 agent 过程，不随单次模型请求或工具执行闪烁。

信号：state_changed("thinking") 有对话进行中
      state_changed("done")     全部对话结束 → 庆祝一次（桌宠端 one-shot 播完自动回 idle）
      state_changed("error")    对话失败
"""
import json
import os
import time

from PySide6.QtCore import QObject, QTimer, Signal

TURN_EVENTS = {"turn.started": +1, "turn.completed": -1, "turn.failed": -1}
# zcode 被杀/崩溃时 turn 永远不闭合：活跃期间日志（含 memory_sample 心跳）这么久没增长就视为已结束
STALE_SEC = 180


class ZcodeWatcher(QObject):
    state_changed = Signal(str)

    def __init__(self, log_dir: str, parent=None, poll_ms: int = 1500, stale_sec: float = STALE_SEC):
        super().__init__(parent)
        self._log_dir = log_dir
        self._path = None
        self._offset = 0           # 已消费的完整行末尾
        self._active_turns = 0
        self._stale_sec = stale_sec
        self._last_growth = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(poll_ms)
        self._timer.timeout.connect(self._poll)

    def start(self):
        try:
            self._baseline()  # 启动对账：zcode 已在进行中的对话 → 直接进思考
        except OSError as e:  # 日志恰好被轮转/删除：不能让桌宠起不来
            print(f"[zcode] 基线扫描失败: {e}")
        self._timer.start()

    # ---------- 内部 ----------

    def _newest_log(self):
        try:
            files = [f for f in os.listdir(self._log_dir) if f.endswith(".jsonl")]
            return os.path.join(self._log_dir, max(files)) if files else None
        except OSError:
            return None

    def _baseline(self):
        """扫描最新日志尾部（512KB），把未闭合的 turn 计为初始活跃数。"""
        path = self._newest_log()
        if not path or not os.path.exists(path):
            return
        self._path = path
        size = os.path.getsize(path)   # OSError 由 start() 兜底
        with open(path, "rb") as f:
            if size > 512 * 1024:
                f.seek(size - 512 * 1024)
                f.readline()  # 丢弃截断的半行
            data = f.read()
        self._offset = size
        active = 0
        for line in data.split(b"\n"):
            # 逐步累加并夹到 0：截断尾部开头的孤立 completed 不能抵消后面真正进行中的 turn
            active = max(0, active + TURN_EVENTS.get(self._event_of(line), 0))
        # 日志很久没写过（zcode 早已退出）：未闭合的 turn 是崩溃残留，不算进行中
        try:
            idle = time.time() - os.path.getmtime(path)
        except OSError:
            idle = 0
        self._active_turns = active if idle < self._stale_sec else 0
        self._last_growth = time.monotonic()
        if self._active_turns > 0:
            self.state_changed.emit("thinking")

    @staticmethod
    def _event_of(line: bytes):
        try:
            return json.loads(line).get("event")
        except Exception:
            return None

    def _poll(self):
        path = self._newest_log()
        if path is None:
            return
        if path != self._path:  # 跨天新文件：从头消费（跨午夜未闭合的 turn 忽略）
            self._path = path
            self._offset = 0
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        if size <= self._offset:
            if size < self._offset:  # 文件被截断/重写
                self._offset = 0
            self._check_stale()
            return
        try:
            with open(path, "rb") as f:
                f.seek(self._offset)
                data = f.read()
        except OSError:
            return
        self._last_growth = time.monotonic()
        cut = data.rfind(b"\n")  # 只消费完整行，半行等写完下次再读
        if cut < 0:
            return
        self._offset += cut + 1
        for line in data[:cut].split(b"\n"):
            self._consume(self._event_of(line))

    def _check_stale(self):
        if self._active_turns > 0 and time.monotonic() - self._last_growth >= self._stale_sec:
            self._active_turns = 0
            self.state_changed.emit("idle")   # 崩溃残留：静默回待机，不庆祝也不报错

    def _consume(self, ev: str | None):
        if ev == "turn.started":
            if self._active_turns == 0:
                self.state_changed.emit("thinking")
            self._active_turns += 1
        elif ev in ("turn.completed", "turn.failed"):
            self._active_turns = max(self._active_turns - 1, 0)
            if self._active_turns == 0:
                self.state_changed.emit("done" if ev == "turn.completed" else "error")
            # 仍有其他对话进行中 → 保持思考，不打断
