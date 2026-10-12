"""第五轮-第二轮回归：会话级 busy、统一 turn_ended、流式中断、上下文裁剪、轮次上限、本地提示不进上下文。"""
import json
import os
import sys
import tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication

from pet import chat_panel as cp
from pet.chat_panel import ChatPanel, MAX_TOOL_ROUNDS
from pet.glm_client import GlmClient

app = QApplication.instance() or QApplication([])


class _Cfg(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)

    def save(self):
        pass


class _Glm(QObject):
    thinking_started = Signal()
    chunk = Signal(str)
    finished = Signal(str, dict)
    failed = Signal(str)
    tool_calls_finished = Signal(list)

    def __init__(self):
        super().__init__()
        self._full = ""
        self.busy = False
        self.interrupted_text = ""
        self.sent = []

    def send(self, messages, model=None, tools=None, stream=True, config=None):
        self.sent.append(messages)


class _Store:
    def summary_for(self, _now):
        return "无安排"


def _panel(**over):
    cp.HISTORY_PATH = os.path.join(tempfile.mkdtemp(), "h.json")
    cfg = _Cfg(api_key="k", api_base="https://t.invalid/v1", chat_model="m1", chat_models=["m1"],
               max_history_messages=20, max_tokens=128, thinking_effort="off", app_aliases={})
    cfg.update(over)
    glm = _Glm()
    p = ChatPanel(cfg, glm, _Store())
    p.toolhost.run = lambda name, args: (True, f"{name} ok")
    ended = []
    p.turn_ended.connect(ended.append)
    return p, glm, ended


class _ManualThread:
    """收集 worker，测试里手动执行，模拟"工具回传线程还没回来"。"""
    pending = []

    def __init__(self, target, daemon):
        self.target = target

    def start(self):
        _ManualThread.pending.append(self.target)


def test_send_blocked_while_tool_roundtrip_in_flight():
    old = cp.threading.Thread
    cp.threading.Thread = _ManualThread
    try:
        p, glm, ended = _panel()
        p.input.setPlainText("打开记事本")
        p.send()
        assert len(glm.sent) == 1 and p.busy
        glm.tool_calls_finished.emit([{"id": "c1", "function": {"name": "list_apps", "arguments": "{}"}}])
        assert p.busy, "工具回传排队期间会话仍忙"
        assert not glm.busy and p.busy, "glm 空闲但会话仍忙"
        p.input.setPlainText("第二句")
        p.send()   # 等价于回车/Ctrl+Enter 绕过按钮
        assert len(glm.sent) == 1, "工具回传期间不能发起新请求"
        assert [m["role"] for m in p.history].count("user") == 1
        p.tool_round_done.emit("好了", [], {})
        assert ended == ["done"] and not p.busy and p.send_btn.isEnabled()
        assert not p._render_timer.isActive()
        p.close()
    finally:
        cp.threading.Thread = old
        _ManualThread.pending.clear()


def test_tool_round_limit_stops_before_executing_extra_round():
    p, glm, ended = _panel()
    calls = []
    p.toolhost.run = lambda name, args: (calls.append(name) or True, "ok")
    p._busy = True
    p.history.append({"role": "user", "content": "x"})
    p._continue_nonstream = lambda: None
    for i in range(MAX_TOOL_ROUNDS + 1):
        p._handle_tool_calls([{"id": f"c{i}", "function": {"name": f"t{i}", "arguments": "{}"}}])
    assert len(calls) == MAX_TOOL_ROUNDS, calls
    assert ended == ["error"] and not p.busy
    p.close()


def test_failed_paths_emit_turn_ended_and_partial_is_local():
    p, glm, ended = _panel()
    p._busy = True
    p._render_timer.start()
    glm.interrupted_text = "说到一半"
    glm.failed.emit("连接中断")
    assert ended == ["error"] and not p._render_timer.isActive()
    last = p.history[-1]
    assert last.get("_local") and "说到一半" in last["content"]
    msgs = p._context_messages()
    assert all("说到一半" not in m["content"] for m in msgs), "本地提示/半截回复不进模型上下文"
    p.close()


def test_context_keeps_current_tool_chain_with_tiny_window():
    p, glm, ended = _panel(max_history_messages=1)
    p.history = [
        {"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "旧回答"},
        {"role": "user", "content": "打开两个应用"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "a"}, {"id": "b"}]},
        {"role": "tool", "tool_call_id": "a", "content": "ok"},
        {"role": "tool", "tool_call_id": "b", "content": "ok"},
    ]
    roles = [m["role"] for m in p._context_messages()]
    assert roles == ["system", "user", "assistant", "tool", "tool"], roles
    p.close()


def test_dict_arguments_and_missing_id():
    p, glm, ended = _panel()
    got = []
    p.toolhost.run = lambda name, args: (got.append(args) or True, "ok")
    p._continue_nonstream = lambda: None
    p._busy = True
    p._handle_tool_calls([{"function": {"name": "open_app", "arguments": {"app": "微信"}}}])
    assert got == [{"app": "微信"}]
    tc = p.history[-2]["tool_calls"][0]
    assert tc["id"] and p.history[-1]["tool_call_id"] == tc["id"]
    p.close()


class _Reply:
    def __init__(self, raw=b"", status=200, error=QNetworkReply.NoError, error_text=""):
        self.raw, self.status, self.err, self.err_text = raw, status, error, error_text

    def readAll(self):
        r, self.raw = self.raw, b""
        return r

    def attribute(self, _a):
        return self.status

    def error(self):
        return self.err

    def errorString(self):
        return self.err_text

    def deleteLater(self):
        pass


def test_stream_interrupted_mid_reply_is_failure():
    c = GlmClient(_Cfg(api_base="https://u/v1", api_key="k", chat_model="m", max_tokens=1,
                       thinking_effort="off"))
    fin, fail = [], []
    c.finished.connect(lambda *a: fin.append(a))
    c.failed.connect(fail.append)
    c._full = "半截"
    c._reply = _Reply(status=200, error=QNetworkReply.RemoteHostClosedError, error_text="closed")
    c._on_finished()
    assert not fin and fail and c.interrupted_text == "半截"


def test_stream_dict_arguments_concat():
    c = GlmClient(_Cfg(api_base="https://u/v1", api_key="k", chat_model="m", max_tokens=1,
                       thinking_effort="off"))
    line = {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "x",
            "function": {"name": "open_app", "arguments": {"app": "a"}}}]}}]}
    c._handle_line(b"data: " + json.dumps(line).encode())
    assert json.loads(c._tool_calls[0]["function"]["arguments"]) == {"app": "a"}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("第五轮-第二轮回归测试通过 ✔")
