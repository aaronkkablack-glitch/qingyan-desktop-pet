"""GLM 客户端协议边界测试：SSE、HTTP 错误、取消和工具信号。"""
import json
import os
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QNetworkRequest, QNetworkReply

from pet.glm_client import GlmClient

app = QCoreApplication.instance() or QCoreApplication([])


class _Cfg(dict):
    pass


class _Reply:
    def __init__(self, raw=b"", status=200, error=QNetworkReply.NoError, error_text=""):
        self.raw = raw
        self.status = status
        self.err = error
        self.error_text = error_text
        self.aborted = False
        self.deleted = False

    def readAll(self):
        raw, self.raw = self.raw, b""
        return raw

    def attribute(self, key):
        return self.status if key == QNetworkRequest.HttpStatusCodeAttribute else None

    def error(self):
        return self.err

    def errorString(self):
        return self.error_text

    def url(self):
        class Url:
            def toString(self):
                return "https://unit.test/chat/completions"
        return Url()

    def deleteLater(self):
        self.deleted = True

    def abort(self):
        self.aborted = True
        self.err = QNetworkReply.OperationCanceledError
        self.error_text = "Operation canceled"


def _client():
    return GlmClient(_Cfg(api_base="https://unit.test/v1", api_key="key",
                          chat_model="test", max_tokens=128, thinking_effort="off"))


def test_sse_split_frames_and_malformed_frame():
    c = _client()
    chunks, errors, finished = [], [], []
    c.chunk.connect(chunks.append)
    c.failed.connect(errors.append)
    c.finished.connect(lambda text, usage: finished.append((text, usage)))
    c._reply = _Reply()
    c._reply.raw = b"data: {\"choices\":[{\"delta\":{\"content\":\"Hi\"}}]}\n"
    c._on_ready()
    c._reply.raw = b"data: not-json\n\ndata: {\"choices\":[{\"delta\":{\"content\":\"!\"}}]}\n\n"
    c._on_ready()
    c._reply = _Reply(status=200)
    c._on_finished()
    assert chunks == ["Hi", "!"]
    assert finished and finished[0][0] == "Hi!"
    assert not errors


def test_stream_http_error_emits_failed_and_clears_busy():
    c = _client()
    errors = []
    c.failed.connect(errors.append)
    payload = b'data: {"error":{"message":"bad request"}}\n'
    c._reply = _Reply(payload, status=400, error=QNetworkReply.ContentAccessDenied,
                      error_text="HTTP 400")
    c._on_finished()
    assert not c.busy
    assert errors and "API 错误" in errors[0]


def test_nonstream_http_error_emits_failed():
    c = _client()
    errors = []
    c.failed.connect(errors.append)
    c._reply = _Reply(b'{"error":{"message":"rate limited"}}', status=429,
                      error=QNetworkReply.ContentAccessDenied, error_text="HTTP 429")
    c._on_finished_nonstream()
    assert not c.busy
    assert errors and "rate limited" in errors[0]


def test_cancel_aborts_and_finished_handler_reports_failure():
    c = _client()
    errors = []
    c.failed.connect(errors.append)
    reply = _Reply(error=QNetworkReply.NoError)
    c._reply = reply
    c.cancel()
    assert reply.aborted
    c._on_finished()
    assert not c.busy
    assert errors and "API 错误" in errors[0]


def test_stream_tool_calls_do_not_emit_normal_finished():
    c = _client()
    normal, calls = [], []
    c.finished.connect(lambda *args: normal.append(args))
    c.tool_calls_finished.connect(calls.append)
    c._tools = [{"type": "function"}]
    c._tool_calls = {0: {"id": "call-1", "type": "function",
                         "function": {"name": "list_apps", "arguments": "{}"}}}
    c._reply = _Reply()
    c._on_finished()
    assert not normal
    assert len(calls) == 1 and calls[0][0]["id"] == "call-1"


def test_nonstream_tool_calls_do_not_emit_normal_finished():
    c = _client()
    normal, calls = [], []
    c.finished.connect(lambda *args: normal.append(args))
    c.tool_calls_finished.connect(calls.append)
    payload = {"choices": [{"message": {"content": "", "tool_calls": [{"id": "call-2"}]}}]}
    c._reply = _Reply(json.dumps(payload).encode())
    c._on_finished_nonstream()
    assert not normal
    assert calls == [[{"id": "call-2"}]]


if __name__ == "__main__":
    test_sse_split_frames_and_malformed_frame()
    test_stream_http_error_emits_failed_and_clears_busy()
    test_nonstream_http_error_emits_failed()
    test_cancel_aborts_and_finished_handler_reports_failure()
    test_stream_tool_calls_do_not_emit_normal_finished()
    test_nonstream_tool_calls_do_not_emit_normal_finished()
    print("GLM 客户端协议边界测试通过 ✔")
