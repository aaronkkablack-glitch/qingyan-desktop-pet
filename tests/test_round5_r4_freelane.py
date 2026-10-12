"""第五轮-第四轮回归（白嫖代理加固）：Host/Origin/Content-Type/大小校验、整包 JSON→delta SSE、
上游非 JSON → 502（不掐连接）、SSE 判定跳过心跳/event 行、classify 不误判正文、401/403 映射 502。
全部用假上游（替换 freelane._OPENER），不出网。"""
import http.client
import json
import os
import sys
import tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import urllib.error

from freelane import freelane as fl


# ---------------------------------------------------------------- 假上游
class _FakeResp:
    def __init__(self, body: bytes, ctype: str, chunk: int = 4096):
        self._buf = io.BytesIO(body)
        self.headers = {"Content-Type": ctype}
        self._chunk = chunk

    def read1(self, n=-1):
        return self._buf.read(min(n, self._chunk) if n and n > 0 else self._chunk)

    def read(self, n=-1):
        return self._buf.read() if n is None or n < 0 else self._buf.read(n)

    def close(self):
        pass


class _FakeOpener:
    """按队列依次返回预设响应；元素为 _FakeResp 或 (status, body) 表示 HTTPError。"""
    def __init__(self):
        self.queue = []
        self.calls = []

    def open(self, req, timeout=None):
        self.calls.append(json.loads(req.data.decode("utf-8")) if req.data else None)
        item = self.queue.pop(0)
        if isinstance(item, tuple):
            status, body = item
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(body))
        return item


_fake = _FakeOpener()
fl._OPENER = _fake
_tmp = tempfile.mkdtemp()
_proxy = fl.FreelaneProxy(data_dir=_tmp)
_proxy.port = 0                      # 临时端口，不和真桌宠的 8787 抢
PORT = _proxy.start()
assert PORT, "代理没起来"


def _req(method="POST", path="/v1/chat/completions", body=b"{}", headers=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    c.putheader("Host", host if host is not None else f"127.0.0.1:{PORT}")
    h = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    h.update(headers or {})
    for k, v in h.items():
        if v is not None:
            c.putheader(k, v)
    c.endheaders()
    if body and method == "POST":
        c.send(body)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, r.getheader("Content-Type") or "", data


def _chat(stream=False, model="space-bunny-free"):
    return json.dumps({"model": model, "stream": stream,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()


def _completion(content="你好", reasoning=None, tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if reasoning:
        msg["reasoning_content"] = reasoning
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return json.dumps({"id": "c1", "object": "chat.completion", "model": "m",
                       "choices": [{"index": 0, "message": msg,
                                    "finish_reason": "tool_calls" if tool_calls else "stop"}],
                       "usage": {"total_tokens": 5}}).encode()


def _sse_frames(data: bytes):
    out = []
    for line in data.decode("utf-8").splitlines():
        if line.startswith("data:"):
            p = line[5:].strip()
            out.append(p if p == "[DONE]" else json.loads(p))
    return out


def test_request_gatekeeping():
    """Host 非回环/端口不符、带 Origin、非 JSON Content-Type、非数字/超大 Content-Length 都被拒。"""
    assert _req(host="evil.example.com")[0] == 403
    assert _req(host=f"127.0.0.1:{PORT + 1}")[0] == 403
    assert _req(headers={"Origin": "http://evil.example.com"})[0] == 403
    assert _req(method="GET", path="/health", body=b"", headers={"Origin": "null"})[0] == 403
    assert _req(headers={"Content-Type": "text/plain"})[0] == 415
    assert _req(headers={"Content-Length": "abc"}, body=b"")[0] == 400
    assert _req(headers={"Content-Length": str(fl.MAX_BODY + 1)}, body=b"")[0] == 413
    assert not _fake.calls, "被拒请求不应打到上游"
    # 桌宠自己的客户端形态（127.0.0.1/localhost Host、application/json; charset、无 Origin）放行
    assert _req(method="GET", path="/health", body=b"")[0] == 200
    assert _req(method="GET", path="/health", body=b"", host=f"localhost:{PORT}")[0] == 200
    _fake.queue.append(_FakeResp(_completion(), "application/json"))
    st, _, data = _req(body=_chat(), headers={"Content-Type": "application/json; charset=utf-8"})
    assert st == 200 and json.loads(data)["choices"][0]["message"]["content"] == "你好"


def test_urllib_client_passes():
    """与 chat_panel/settings_dialog 相同的 urllib 写法能通过校验。"""
    import urllib.request
    _fake.queue.append(_FakeResp(_completion("ok"), "application/json"))
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=_chat(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer freelane"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    d = json.loads(opener.open(req, timeout=10).read())
    assert d["choices"][0]["message"]["content"] == "ok"


def test_json_to_delta_sse():
    """客户端要流、上游回整包 JSON：转成 delta 帧（content/reasoning/tool_calls 带 index）+ finish + [DONE]。"""
    tcs = [{"id": "call_1", "type": "function",
            "function": {"name": "open_app", "arguments": "{\"app\":\"qq\"}"}}]
    _fake.queue.append(_FakeResp(_completion("正文", reasoning="想想", tool_calls=tcs), "application/json"))
    st, ctype, data = _req(body=_chat(stream=True))
    assert st == 200 and "text/event-stream" in ctype
    frames = _sse_frames(data)
    assert frames[-1] == "[DONE]"
    delta = frames[0]["choices"][0]["delta"]
    assert "message" not in frames[0]["choices"][0]
    assert delta["content"] == "正文" and delta["reasoning_content"] == "想想"
    assert delta["tool_calls"][0]["index"] == 0
    assert delta["tool_calls"][0]["function"]["name"] == "open_app"
    fin = frames[-2]
    assert fin["choices"][0]["finish_reason"] == "tool_calls" and fin["usage"]["total_tokens"] == 5


def test_non_json_upstream_502():
    """上游回 HTML（非 SSE 非 JSON），流式/非流式都回 502 JSON，而不是掐连接。"""
    for stream in (True, False):
        _fake.queue.append(_FakeResp(b"<html>bad gateway</html>", "text/html"))
        st, ctype, data = _req(body=_chat(stream=stream))
        assert st == 502, (stream, st, data)
        assert json.loads(data)["error"]["type"] == "bad_upstream"


def test_sse_with_keepalive_prefix():
    """SSE 首块是心跳注释/event 行/短读：仍按流转发，不被当成 JSON。"""
    body = (b": keep-alive\n\nevent: message\n"
            b'data: {"choices":[{"index":0,"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n')
    # 有 SSE content-type
    _fake.queue.append(_FakeResp(body, "text/event-stream", chunk=3))
    st, _, data = _req(body=_chat(stream=True))
    assert st == 200 and _sse_frames(data)[0]["choices"][0]["delta"]["content"] == "hi"
    # 无 SSE content-type + 每次只读 3 字节
    _fake.queue.append(_FakeResp(body, "application/json", chunk=3))
    st, _, data = _req(body=_chat(stream=True))
    assert st == 200 and _sse_frames(data)[0]["choices"][0]["delta"]["content"] == "hi"
    assert fl._sse_verdict(b"\n: ping\n") is None
    assert fl._sse_verdict(b"da") is None
    assert fl._sse_verdict(b"{\"id\"") is False
    assert fl._sse_verdict(b": x\nevent: m\ndata: {}") is True


def test_classify_not_misfiring():
    """正常补全正文里含 region/error/free tier 等词不算错误；顶层 error 字段才分类。"""
    ok = _completion('出现 "error" 字样、region 与 free tier、not supported 都只是正文')
    assert fl.classify(200, ok) == ("ok", "")
    assert fl.classify(200, b'{"error":{"type":"FreeTierError","message":"x"}}')[0] == "gate"
    assert fl.classify(401, b'{"error":{"type":"ModelError","message":"Model is unavailable"}}')[0] == "model"
    assert fl.classify(403, b'{"error":{"message":"not available in your region"}}')[0] == "region"
    assert fl.classify(429, b'{"error":{"message":"slow down"}}')[0] == "quota"
    assert fl.classify(500, b"<html>oops</html>")[0] == "other"
    assert fl.classify(200, b'{"error": null, "choices": []}')[0] == "ok"


def test_upstream_401_403_mapped_502():
    """上游 401/403（模型不可路由/资格门且回退也失败）不透传，映射 502 并带分类 type。"""
    err = json.dumps({"error": {"type": "FreeTierError", "message": "nope"}}).encode()
    _fake.queue.extend([(403, err), (403, err)])
    st, _, data = _req(body=_chat(model="other-free"))
    assert st == 502 and json.loads(data)["error"]["type"] == "gate"
    assert len(_fake.calls) >= 2 and _fake.calls[-1]["model"] == _proxy.fallback_model


def test_log_rotation_and_atomic_state():
    """日志超限轮转为 .1；state 文件原子写；日志里会话 id 截断。"""
    _proxy.log_path.write_text("x" * (fl.LOG_CAP + 10), encoding="utf-8")
    _proxy.log("rotate me")
    assert (_proxy.log_path.with_name(_proxy.log_path.name + ".1")).exists()
    assert "rotate me" in _proxy.log_path.read_text(encoding="utf-8")
    s = fl._load_session(_proxy.state_path, new=True)
    assert json.loads(_proxy.state_path.read_text(encoding="utf-8"))["session"] == s
    assert not _proxy.state_path.with_name(_proxy.state_path.name + ".tmp").exists()
    assert fl._short_session(s) != s and s.startswith(fl._short_session(s)[:-1])
    assert fl.running_port() == PORT


if __name__ == "__main__":
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn()
                print(f"{name} 通过 ✔")
    finally:
        _proxy.stop()
