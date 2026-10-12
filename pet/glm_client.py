"""GLM 开放平台流式客户端（QNetworkAccessManager，单线程异步，无额外依赖）。

已验证的事实（2026-10-02，勿凭记忆改）：
- endpoint: {api_base}/chat/completions，Bearer 认证，key 形如 id.secret
- 模型 glm-5.3-flash / glm-5.3 均可用；这两个模型始终思考，
  thinking 只支持 {"type":"enabled","effort":"low|high|max"}，传 disabled 会 400
- SSE: "data: {...}" 行 + "data: [DONE]"；delta 里先来 reasoning_content（思考），
  再来 content（正文）；末尾有一个带 usage 的块（需 stream_options.include_usage）
- 不设人设约束时思考可长达 1000+ token（首字 28s）；系统提示词里写
  "直接说、不犹豫" 可压到 ~50 token（首字 2.2s）——DEFAULT_PERSONA 已包含
"""
import json
import copy

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest


class GlmClient(QObject):
    thinking_started = Signal()          # 开始输出思考（还没正文）
    chunk = Signal(str)                  # 正文增量
    finished = Signal(str, dict)         # (完整正文, usage dict，可能为空)
    failed = Signal(str)
    tool_calls_finished = Signal(list)   # 完整 tool_calls 列表（OpenAI 格式）

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._cfg = config
        self._manager = QNetworkAccessManager(self)
        # 与工具回传（net.DIRECT_OPENER）一致：固定直连，不吃系统代理缓存（开发日志 10061 一节）
        self._manager.setProxy(QNetworkProxy(QNetworkProxy.NoProxy))
        self._reply: QNetworkReply | None = None
        self._buf = b""
        self._full = ""
        self._usage: dict = {}
        self._thinking_notified = False
        self._tools: list | None = None       # 本次请求携带的 tools
        self._tool_calls: dict = {}           # index -> {id, name, arguments} 流式拼接
        self.interrupted_text = ""            # 流式中途断开时已收到的半截正文（随 failed 一起给上层）

    @property
    def busy(self) -> bool:
        return self._reply is not None

    def send(self, messages: list, model: str | None = None,
             tools: list | None = None, stream: bool = True, config=None):
        """stream=True 走 SSE 流式（首聊体验好）；工具结果回传的下一轮用 stream=False
        （GLM 流式对"tool 结果消息"上下文会挂起不响应，非流式正常，2026-10-04 实测）。"""
        if self.busy:
            self.failed.emit("上一条还在回复中")
            return
        if config is not None:
            self._cfg = copy.deepcopy(config)
        self._stream_mode = stream
        body = self._build_body(messages, model, tools, stream)
        self._tools = tools
        self._tool_calls = {}
        req = QNetworkRequest(QUrl(f"{self._cfg['api_base']}/chat/completions"))
        req.setRawHeader(b"Authorization", f"Bearer {self._cfg['api_key']}".encode())
        req.setRawHeader(b"Content-Type", b"application/json")
        req.setTransferTimeout(180_000)
        self._buf = b""
        self._full = ""
        self.interrupted_text = ""
        self._usage = {}
        self._thinking_notified = False
        if stream:
            self._reply = self._manager.post(req, json.dumps(body).encode())
            self._reply.readyRead.connect(self._on_ready)
            self._reply.finished.connect(self._on_finished)
        else:
            self._reply = self._manager.post(req, json.dumps(body).encode())
            self._reply.finished.connect(self._on_finished_nonstream)

    def _build_body(self, messages: list, model: str | None,
                    tools: list | None, stream: bool) -> dict:
        body = {
            "model": model or self._cfg["chat_model"],
            "messages": messages,
            "max_tokens": self._cfg.get("max_tokens", 2048),
        }
        # GLM-5.3 系始终思考且只支持 enabled 档位；thinking_effort=off 时不发该字段
        # （接 DeepSeek 等其他 OpenAI 兼容模型时避免未知参数报错）
        effort = self._cfg.get("thinking_effort", "low")
        if effort and effort != "off":
            body["thinking"] = {"type": "enabled", "effort": effort}
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        if tools:
            body["tools"] = tools
        return body

    def cancel(self, silent=False):
        reply = self._reply
        if reply is None:
            return
        if silent:
            # 断开旧 reply 的回调再 abort，下一轮不会消费旧请求的事件。
            self._reply = None
            reply.finished.disconnect()
            if self._stream_mode:
                reply.readyRead.disconnect()
            reply.abort()
            reply.deleteLater()
        else:
            reply.abort()

    def _on_ready(self):
        if self._reply is None:
            return
        self._buf += bytes(self._reply.readAll())
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            self._handle_line(line.strip())

    def _handle_line(self, line: bytes):
        if not line.startswith(b"data:"):
            return
        payload = line[5:].strip()
        if payload == b"[DONE]":
            return
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return
        if data.get("usage"):
            self._usage = data["usage"]
        choices = data.get("choices") or []
        if not choices:
            return
        delta = choices[0].get("delta", {})
        if delta.get("tool_calls"):
            # 流式 tool_calls 拼接：按 index 累积 id/name/arguments 片段
            for tc in delta["tool_calls"]:
                idx = tc.get("index", 0)
                slot = self._tool_calls.setdefault(idx, {"id": "", "type": "function",
                                                         "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                if tc.get("type"):
                    slot["type"] = tc["type"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] += fn["name"]
                args = fn.get("arguments")
                if isinstance(args, dict):     # 部分兼容服务直接给对象而非 JSON 字符串片段
                    slot["function"]["arguments"] = json.dumps(args, ensure_ascii=False)
                elif args:
                    slot["function"]["arguments"] += args
        if delta.get("content"):
            self._full += delta["content"]
            self.chunk.emit(delta["content"])
        elif delta.get("reasoning_content") and not self._thinking_notified:
            self._thinking_notified = True
            self.thinking_started.emit()

    def _on_finished_nonstream(self):
        """非流式（工具轮次）完成：解析完整 message。"""
        reply, self._reply = self._reply, None
        if reply is None:
            return
        raw = bytes(reply.readAll())
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        err = reply.errorString() if reply.error() != QNetworkReply.NoError else ""
        reply.deleteLater()
        if (status is not None and status >= 400) or err:
            msg = err or f"HTTP {status}"
            try:
                msg = json.loads(raw.decode("utf-8", "replace")).get("error", {}).get("message", msg)
            except Exception:
                pass
            self.failed.emit(f"API 错误：{msg}")
            return
        try:
            d = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            self.failed.emit("非流式响应解析失败")
            return
        if not isinstance(d, dict) or not isinstance(d.get("choices"), list) or not d["choices"]:
            self.failed.emit("非流式响应缺少有效 choices")
            return
        self._usage = d.get("usage") or {}
        msg = d["choices"][0].get("message", {})
        if not isinstance(msg, dict):
            self.failed.emit("非流式响应 message 格式错误")
            return
        calls = msg.get("tool_calls") or []
        if calls:
            self._full = msg.get("content") or ""
            self.tool_calls_finished.emit(calls)
            return
        if not msg.get("content"):
            self.failed.emit("空回复")
            return
        self.finished.emit(msg.get("content") or "", self._usage)

    def _on_finished(self):
        reply, self._reply = self._reply, None
        if reply is None:
            return
        self._buf += bytes(reply.readAll())
        for line in self._buf.split(b"\n"):
            self._handle_line(line.strip())
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        err = reply.errorString() if reply.error() != QNetworkReply.NoError else ""
        reply.deleteLater()
        if err and self._full and not (status is not None and status >= 400):
            # 流式中途断开：已收到的半截正文不能当完整回答；交给上层按失败收尾、保留展示
            self.interrupted_text = self._full
            self.failed.emit(f"连接中断，回复不完整：{err}")
            return
        if (status is not None and status >= 400) or err:
            msg = err or f"HTTP {status}"
            try:
                tail = self._buf.decode("utf-8", "replace")
                if '"error"' in tail:
                    msg = json.loads(tail.split("data:")[-1]).get("error", {}).get("message", msg)
            except Exception:
                pass
            self.failed.emit(f"API 错误：{msg}")
            return
        # 工具调用优先：模型决定调用工具时通常无正文
        if self._tool_calls and self._tools:
            calls = [self._tool_calls[k] for k in sorted(self._tool_calls)]
            self.tool_calls_finished.emit(calls)
            return
        if not self._full:
            self.failed.emit("空回复（模型思考超限？可调大 max_tokens）")
            return
        self.finished.emit(self._full, self._usage)
