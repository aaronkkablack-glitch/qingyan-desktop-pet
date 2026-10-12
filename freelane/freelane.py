# -*- coding: utf-8 -*-
"""freelane —— 白嫖通道：OpenCode Zen 免费车道 → 本地 OpenAI 兼容端点。

双形态：
- **内嵌**（桌宠用）：`FreelaneProxy(...).start()` 在后台线程常驻本机回环，
  桌宠设置里的「白嫖通道」开关决定是否真的走它（关着只是躺着，不出网）；
- **独立**：`python freelane.py`，给调试 / 其它工具（如以后的 agent）用。

原理：上游 `https://opencode.ai/zen/v1/*` 的公开免密车道（`Authorization: Bearer public`），
按客户端指纹取用：6 个 x-opencode-* 头 + UA(>=1.17) + 请求体 tools 必须包含
bash/glob/grep/read 四件套（本代理对带工具的请求自动补自禁用诱饵）。额度按会话（ses_*）计，
会话 id 持久化（删 state 文件 = 换新会话）。

只监听 127.0.0.1；聊天内容会明文发往上游（免费模型可能用于训练）。

实测（2026-10-08）：13 个免费模型里仅 space-bunny-free 全通（流式 / 工具调用 / 用量）；
其余多为 401 ModelError（在目录但不可路由）或 403 FreeTierError（门更严）→ 自动回退 fallback_model。
GLM 的 thinking 字段上游忽略不报错，本代理仍会剥掉；非流式不发 stream_options。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UPSTREAM = "https://opencode.ai"
CLIENT_UA = "opencode/1.18.31"          # 上游要求 >= 1.17
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_FALLBACK = "space-bunny-free"
DEFAULT_ALIASES = {                     # 桌宠里残留的 GLM 模型名 → 免费模型
    "glm-5.3-flash": DEFAULT_FALLBACK,
    "glm-5.3": DEFAULT_FALLBACK,
}
QUARTET = ("bash", "glob", "grep", "read")   # 免费车道的工具指纹四件套
DECOY_DESC = "This tool is currently unavailable and must not be used."
UPSTREAM_TIMEOUT = 300
LOG_CAP = 2 * 1024 * 1024
MAX_BODY = 8 * 1024 * 1024              # 请求体上限（超出 413）
CLIENT_TIMEOUT = 30                     # 读客户端请求的 socket 超时（秒）
MAX_CONCURRENT = 8                      # 同时处理的 POST 上限（超出 503）
SNIFF_CAP = 64 * 1024                   # 无 SSE content-type 时最多嗅探多少字节再下结论

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# 直连上游：显式禁用 urllib 的一切代理（系统代理 / 环境变量代理都不走）。
# 坑（2026-10-09 实锤）：urllib.request.urlopen 会把**首次调用时**的代理设置缓存在
# 全局 opener 里——用户开过又关掉网络代理后，长驻进程会一直往已关闭的代理端口发请求，
# 报 WinError 10061"目标计算机积极拒绝"。免费车道实测直连可达，这里固定直连。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ---------------------------------------------------------------- 铸号
def _b62(data: bytes) -> str:
    return "".join(BASE62[b % 62] for b in data)


def _hex6(value: int) -> str:
    return "".join(f"{(value >> (40 - 8 * i)) & 0xFF:02x}" for i in range(6))


def mint_session() -> str:
    value = (~((int(time.time() * 1000) << 12) + 1)) & ((1 << 48) - 1)
    return "ses_" + _hex6(value) + _b62(os.urandom(14))


def mint_request_id() -> str:
    value = ((int(time.time() * 1000) << 12) + 1) & ((1 << 48) - 1)
    return "msg_" + _hex6(value) + _b62(os.urandom(14))


def _load_session(state_path: Path, new: bool = False) -> str:
    """会话 id 跨重启保持稳定（额度按会话记，换会话=换额度）。"""
    if not new:
        try:
            s = json.loads(state_path.read_text(encoding="utf-8")).get("session")
            if isinstance(s, str) and s.startswith("ses_"):
                return s
        except (OSError, ValueError):
            pass
    s = mint_session()
    _atomic_write(state_path, json.dumps({"session": s}))
    return s


def _atomic_write(path: Path, text: str) -> None:
    """先写临时文件再 os.replace，避免写一半断电/崩溃留下残缺的 state 文件。"""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def _short_session(s: str) -> str:
    """日志里只露会话 id 前缀（会话 id 等同额度凭据，不整串落盘）。"""
    return (s[:12] + "…") if s else ""


# ---------------------------------------------------------------- 请求改写
def _tool_name(t) -> str:
    if not isinstance(t, dict):
        return ""
    if isinstance(t.get("name"), str):
        return t["name"].strip()
    fn = t.get("function")
    if isinstance(fn, dict) and isinstance(fn.get("name"), str):
        return fn["name"].strip()
    return ""


def fill_quartet(tools: list) -> int:
    """声明了工具时，把缺失的 bash/glob/grep/read 用自禁用诱饵补齐（上游指纹门要求）。"""
    have = {_tool_name(t).lower() for t in tools}
    added = 0
    for name in QUARTET:
        if name in have:
            continue
        tools.append({"type": "function", "function": {
            "name": name, "description": DECOY_DESC,
            "parameters": {"type": "object", "properties": {}}}})
        added += 1
    return added


def prepare_payload(src: dict, aliases: dict) -> tuple[dict, int]:
    body = dict(src)
    body.pop("thinking", None)                       # GLM 专属字段，上游不认
    if not body.get("stream"):
        body.pop("stream_options", None)             # 非流式没有意义，避免未知参数
    model = str(body.get("model") or "")
    if model in aliases:
        body["model"] = aliases[model]
    tools = body.get("tools")
    added = fill_quartet(tools) if isinstance(tools, list) and tools else 0
    return body, added


# ---------------------------------------------------------------- 错误分类
def _err_message(raw: bytes) -> str:
    try:
        d = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return raw.decode("utf-8", "replace")[:200]
    err = d.get("error") if isinstance(d, dict) else None
    if isinstance(err, dict):
        inner = err.get("error")
        if isinstance(inner, dict) and isinstance(inner.get("message"), str):
            return inner["message"]
        if isinstance(err.get("message"), str):
            return err["message"]
    return str(d)[:200]


def _error_text(raw: bytes) -> tuple[bool, str]:
    """返回 (是否带顶层 error 字段, 仅错误部分的小写文本)。

    只看 error 字段本身（type/name/message 等），绝不扫整个响应体——正常补全的正文里
    出现 "region"/"error"/"free tier" 之类的词不能被误判成上游错误。"""
    try:
        d = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return False, raw.decode("utf-8", "replace")[:500].lower()
    if not isinstance(d, dict) or d.get("error") in (None, "", {}, []):
        return False, ""
    err = d["error"]
    text = json.dumps(err, ensure_ascii=False) if not isinstance(err, str) else err
    if isinstance(d.get("type"), str):           # 形如 {"type": "FreeTierError", "error": ...}
        text = d["type"] + " " + text
    return True, text.lower()


def classify(status: int, raw: bytes) -> tuple[str, str]:
    has_err, low = _error_text(raw)
    if not has_err and status < 400:
        return "ok", ""
    detail = _err_message(raw)
    if "freetiererror" in low or "free tier" in low:
        return "gate", detail
    if "not supported" in low or "modelerror" in low or "model is unavailable" in low:
        return "model", detail
    if "region" in low:
        return "region", detail
    if status == 429:
        return "quota", detail
    return "other", detail


def friendly_message(kind: str, model: str, detail: str) -> str:
    if kind == "model":
        return f"模型 {model} 当前不可用（上游：{detail}）"
    if kind == "gate":
        return f"模型 {model} 被免费通道的资格门拒绝（{detail}），换个模型试试"
    if kind == "region":
        return f"当前网络出口被上游地区门拒绝（{detail}）"
    if kind == "quota":
        return "免费通道额度暂时打满（429），等几分钟再聊"
    return f"上游错误（{detail}）"


# ---------------------------------------------------------------- SSE 组装
_SSE_SKIP = (b":", b"event:", b"id:", b"retry:")    # SSE 里可出现在首个 data 之前的行


def _sse_verdict(raw: bytes):
    """判断已读到的字节是不是 SSE：True / False / None（还不能下结论，需要再读）。

    跳过开头的空行、`:` 心跳注释、`event:` / `id:` / `retry:` 行；末尾不完整的半行
    若还可能是 data:/注释等前缀，就先不判（上游短读时首块可能只有几个字节）。"""
    lines = raw.split(b"\n")
    tail = lines.pop()                            # 最后一段没有换行结尾 = 半行
    for line in lines:
        t = line.strip()
        if not t or t.startswith(_SSE_SKIP):
            continue
        return t.startswith(b"data:")
    t = tail.strip()
    if not t:
        return None
    if t.startswith(b"data:"):
        return True
    for p in (b"data:",) + _SSE_SKIP:
        if t.startswith(p) or p.startswith(t):
            return None
    return False


def _looks_sse(raw: bytes) -> bool:
    """完整响应体是否 SSE 帧（非流式分支用：上游偶发用 JSON content-type 回 SSE）。"""
    return _sse_verdict(raw + b"\n") is True


def completion_to_chunks(obj: dict) -> list[dict]:
    """把完整 chat.completion 拆成 delta 形态的 SSE 帧（桌宠客户端只读 choices[].delta）。"""
    base = {"id": obj.get("id") or "chatcmpl-freelane", "object": "chat.completion.chunk",
            "created": obj.get("created") or int(time.time()), "model": obj.get("model") or ""}
    chunks = []
    finals = []
    for i, ch in enumerate(obj.get("choices") or []):
        if not isinstance(ch, dict):
            continue
        idx = ch.get("index", i)
        msg = ch.get("message") or ch.get("delta") or {}
        delta: dict = {"role": msg.get("role") or "assistant"}
        if msg.get("reasoning_content"):
            delta["reasoning_content"] = msg["reasoning_content"]
        if msg.get("content"):
            delta["content"] = msg["content"]
        calls = []
        for j, tc in enumerate(msg.get("tool_calls") or []):
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            calls.append({"index": tc.get("index", j), "id": tc.get("id") or "",
                          "type": tc.get("type") or "function",
                          "function": {"name": fn.get("name") or "", "arguments": args}})
        if calls:
            delta["tool_calls"] = calls
        chunks.append(dict(base, choices=[{"index": idx, "delta": delta, "finish_reason": None}]))
        finals.append({"index": idx, "delta": {},
                       "finish_reason": ch.get("finish_reason") or ("tool_calls" if calls else "stop")})
    last = dict(base, choices=finals)
    if obj.get("usage"):
        last["usage"] = obj["usage"]
    chunks.append(last)
    return chunks


def assemble_sse_text(text: str) -> dict:
    """上游偶发用 JSON content-type 回 SSE 帧（高负载），这里攒成完整补全。"""
    content, reasoning, usage, finish, model, mid = [], [], None, None, None, None
    tools: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            continue
        try:
            d = json.loads(payload)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if d.get("usage"):
            usage = d["usage"]
        model = d.get("model") or model
        mid = d.get("id") or mid
        choices = d.get("choices") or []
        if not choices:
            continue
        ch = choices[0] or {}
        if ch.get("finish_reason"):
            finish = ch["finish_reason"]
        delta = ch.get("delta") or {}
        if delta.get("content"):
            content.append(delta["content"])
        if delta.get("reasoning_content"):
            reasoning.append(delta["reasoning_content"])
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            slot = tools.setdefault(idx, {"id": "", "type": "function",
                                          "function": {"name": "", "arguments": ""}})
            if tc.get("id"):
                slot["id"] = tc["id"]
            if tc.get("type"):
                slot["type"] = tc["type"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                slot["function"]["arguments"] += fn["arguments"]
    msg: dict = {"role": "assistant", "content": "".join(content)}
    if reasoning:
        msg["reasoning_content"] = "".join(reasoning)
    if tools:
        msg["tool_calls"] = [tools[k] for k in sorted(tools)]
    out = {
        "id": mid or "chatcmpl-freelane",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or "",
        "choices": [{"index": 0, "message": msg,
                     "finish_reason": finish or ("tool_calls" if tools else "stop")}],
    }
    if usage:
        out["usage"] = usage
    return out


# ---------------------------------------------------------------- 运行中实例登记
# 设置对话框切到白嫖通道时要知道代理实际端口（被占时 start() 会换随机端口），
# 而 main.py 只把实例放在局部变量里——这里按进程登记，供 running_port() 查询。
_RUNNING: list = []
_RUNNING_LOCK = threading.Lock()


def _register_running(proxy) -> None:
    with _RUNNING_LOCK:
        if proxy not in _RUNNING:
            _RUNNING.append(proxy)


def _unregister_running(proxy) -> None:
    with _RUNNING_LOCK:
        if proxy in _RUNNING:
            _RUNNING.remove(proxy)


def running_port() -> int:
    """本进程里最早启动、仍在运行的内嵌代理端口；没有则 0。"""
    with _RUNNING_LOCK:
        for p in _RUNNING:
            if p.running:
                return int(p.port)
    return 0


# ---------------------------------------------------------------- 代理本体
class FreelaneProxy:
    """可内嵌（桌宠）也可独立运行的白嫖代理。线程安全：只用不可变配置 + 持久化会话。"""

    def __init__(self, data_dir=None, fallback_model=None, aliases=None,
                 host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, log_path=None):
        base = Path(data_dir) if data_dir else Path(__file__).resolve().parent
        self.data_dir = base
        self.fallback_model = str(fallback_model or DEFAULT_FALLBACK)
        self.aliases = dict(DEFAULT_ALIASES)
        if isinstance(aliases, dict):
            self.aliases.update({str(k): str(v) for k, v in aliases.items() if k and v})
        self.host = host
        self.port = int(port or DEFAULT_PORT)
        self.log_path = Path(log_path) if log_path else base / "freelane.log"
        self.state_path = base / "freelane.state.json"
        self.session = ""
        self._httpd = None
        self._thread = None
        self._log_lock = threading.Lock()

    # ---- 日志 ----
    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
        with self._log_lock:
            try:
                print(line, flush=True)      # 独立模式有窗口；pythonw 下 sys.stdout=None 会被吞
            except Exception:
                pass
            try:
                if self.log_path.exists() and self.log_path.stat().st_size > LOG_CAP:
                    # 轮转为 .1（保留上一份，排障时不至于一超限就全丢）
                    os.replace(self.log_path, self.log_path.with_name(self.log_path.name + ".1"))
            except OSError:
                pass
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    # ---- 生命周期 ----
    def start(self, preferred_port=None, new_session: bool = False,
              allow_dynamic: bool = True) -> int:
        """启动代理并返回实际端口；失败返回 0。

        allow_dynamic=True（内嵌）：首选端口被占则换随机端口（桌宠按返回值改内存配置）；
        allow_dynamic=False（独立）：端口被占就失败退出（其它工具需要稳定端点）。
        """
        if self._httpd is not None:
            return self.port
        self.session = _load_session(self.state_path, new=new_session)
        candidates = [int(preferred_port or self.port)]
        if allow_dynamic:
            candidates.append(0)
        else:
            # 先探一下，给"已在运行"一个更友好的提示
            try:
                with socket.create_connection((self.host, candidates[0]), timeout=1):
                    self.log(f"端口 {candidates[0]} 已有服务在监听（可能代理已在运行），本次不启动")
                    return 0
            except OSError:
                pass
        last_err = None
        for port in candidates:
            try:
                httpd = _Server((self.host, port), Handler)
                httpd.proxy = self
                self._httpd = httpd
                self.port = int(httpd.server_address[1])
                _register_running(self)
                break
            except OSError as e:
                last_err = e
        if self._httpd is None:
            self.log(f"代理启动失败：{last_err}")
            return 0
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="freelane-proxy", daemon=True)
        self._thread.start()
        self.log(f"白嫖代理已启动 http://{self.host}:{self.port}/v1 ｜ 会话 {_short_session(self.session)} "
                 f"｜ 回退模型 {self.fallback_model}")
        return self.port

    def stop(self) -> None:
        if self._httpd is None:
            return
        try:
            self._httpd.shutdown()
        except Exception:
            pass
        try:
            self._httpd.server_close()
        except Exception:
            pass
        self._httpd = None
        _unregister_running(self)

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def update_config(self, fallback_model=None, aliases=None) -> None:
        """更新运行中代理的路由配置，不重启本地 HTTP 服务。"""
        if fallback_model:
            self.fallback_model = str(fallback_model)
        if isinstance(aliases, dict):
            merged = dict(DEFAULT_ALIASES)
            merged.update({str(k): str(v) for k, v in aliases.items() if k and v})
            self.aliases = merged

    # ---- 上游 ----
    def upstream_headers(self, stream: bool) -> dict:
        return {
            "content-type": "application/json",
            "authorization": "Bearer public",
            "user-agent": CLIENT_UA,
            "x-opencode-client": "desktop",
            "x-opencode-session": self.session,
            "x-opencode-request": mint_request_id(),
            "x-opencode-project": "global",
            "accept": "text/event-stream" if stream else "*/*",
        }

    def attempt(self, payload: dict, stream: bool):
        """一次上游请求。返回 (kind, ...)：
        ("sse", resp, first_bytes) | ("json", status, raw) | ("completion", status, dict)
        | ("error", status, errkind, detail) | ("neterr", None, "net", detail)"""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{UPSTREAM}/zen/v1/chat/completions", data=data,
                                     headers=self.upstream_headers(stream), method="POST")
        try:
            resp = _OPENER.open(req, timeout=UPSTREAM_TIMEOUT)
        except urllib.error.HTTPError as e:
            raw = e.read()
            kind, detail = classify(e.code, raw)
            return ("error", e.code, kind, detail)
        except Exception as e:  # URLError / timeout / ssl
            return ("neterr", None, "net", f"{type(e).__name__}: {e}")

        if stream:
            read1 = getattr(resp, "read1", None) or resp.read
            ctype = ""
            try:
                ctype = str(resp.headers.get("Content-Type") or "").lower()
            except Exception:
                pass
            first = b""
            try:
                if "text/event-stream" in ctype:
                    # 先信 Content-Type：心跳注释 / event 行 / 短读都不影响判定
                    first = read1(4096) or b""
                    return ("sse", resp, first)
                # 没有 SSE content-type：跳过开头空行/注释/event 行再判断，短读就继续读
                verdict = None
                while verdict is None and len(first) < SNIFF_CAP:
                    chunk = read1(4096) or b""
                    if not chunk:
                        break
                    first += chunk
                    verdict = _sse_verdict(first)
            except Exception as e:
                resp.close()
                return ("neterr", None, "net", f"{type(e).__name__}: {e}")
            if verdict:
                return ("sse", resp, first)
            raw = first
            try:
                raw += resp.read()
            except Exception as e:
                return ("neterr", None, "net", f"{type(e).__name__}: {e}")
            finally:
                resp.close()
            if _looks_sse(raw):                  # 只有心跳/空行开头、后面才出 data 的整包
                try:
                    return ("completion", 200, assemble_sse_text(raw.decode("utf-8", "replace")))
                except Exception as e:
                    return ("error", 200, "other", f"SSE 解析失败: {e}")
            kind, detail = classify(200, raw)
            if kind != "ok":
                return ("error", 200, kind, detail)
            return ("json", 200, raw)

        try:
            raw = resp.read()
        except Exception as e:
            return ("neterr", None, "net", f"{type(e).__name__}: {e}")
        finally:
            resp.close()
        if _looks_sse(raw):
            try:
                return ("completion", 200, assemble_sse_text(raw.decode("utf-8", "replace")))
            except Exception as e:
                return ("error", 200, "other", f"SSE 解析失败: {e}")
        kind, detail = classify(200, raw)
        if kind != "ok":
            return ("error", 200, kind, detail)
        return ("json", 200, raw)


class _Server(ThreadingHTTPServer):
    # Windows 下 SO_REUSEADDR 允许两个进程绑同一端口（不是重连支持），必须关掉
    allow_reuse_address = False
    daemon_threads = True
    proxy: "FreelaneProxy" = None

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)   # 并发上限，超出 503


# ---------------------------------------------------------------- HTTP 处理
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "freelane/1.1"
    timeout = CLIENT_TIMEOUT        # 读请求的 socket 超时：慢速/半开连接不会无限占线程

    def log_message(self, fmt, *args):  # 静音默认访问日志
        pass

    @property
    def proxy(self) -> "FreelaneProxy":
        return self.server.proxy

    def _send_json(self, status: int, obj: dict) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except OSError:
            pass

    def _write_chunk(self, data: bytes) -> None:
        self.wfile.write(f"{len(data):X}\r\n".encode("ascii") + data + b"\r\n")

    def _send_sse_single(self, obj: dict) -> None:
        """把完整补全转成 delta 形态的 SSE 帧发给在等流的调用方（客户端只读 delta）。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()
        frames = completion_to_chunks(obj) if isinstance(obj.get("choices"), list) else [obj]
        payload = "".join("data: " + json.dumps(f, ensure_ascii=False) + "\n\n" for f in frames)
        payload += "data: [DONE]\n\n"
        try:
            self._write_chunk(payload.encode("utf-8"))
            self.wfile.write(b"0\r\n\r\n")
        except OSError:
            pass

    # ------------------------------------------------------------ 来源校验
    def _origin_ok(self) -> bool:
        """防浏览器 CSRF / DNS 重绑定：带 Origin 的一律拒（桌宠客户端不发 Origin），
        Host 必须是回环地址 + 本代理端口。不通过时已回 403。"""
        if self.headers.get("Origin") is not None:
            self._send_json(403, {"error": {"message": "拒绝来自浏览器页面的跨源请求",
                                            "type": "forbidden"}})
            return False
        port = self.server.server_address[1]
        host = str(self.headers.get("Host") or "").strip().lower()
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            self._send_json(403, {"error": {"message": f"Host 不被允许：{host[:60]}",
                                            "type": "forbidden"}})
            return False
        return True

    # ------------------------------------------------------------ POST
    def do_POST(self):
        if not self._origin_ok():
            return
        slots = self.server.slots
        if not slots.acquire(blocking=False):
            self._send_json(503, {"error": {"message": f"代理繁忙（并发超过 {MAX_CONCURRENT}），稍后再试",
                                            "type": "busy"}})
            return
        try:
            self._do_post()
        finally:
            slots.release()

    def _do_post(self):
        p = self.proxy
        path = self.path.split("?", 1)[0].rstrip("/")
        if path not in ("/v1/chat/completions", "/chat/completions"):
            self._send_json(404, {"error": {"message": f"未知路径 {path}"}})
            return
        ctype = str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            self._send_json(415, {"error": {"message": "Content-Type 必须是 application/json"}})
            return
        cl = str(self.headers.get("Content-Length") or "0").strip()
        if not cl.isdigit():
            self._send_json(400, {"error": {"message": "Content-Length 非法"}})
            return
        n = int(cl)
        if n > MAX_BODY:
            self._send_json(413, {"error": {"message": f"请求体过大（上限 {MAX_BODY // 1024 // 1024}MB）"}})
            return
        try:
            raw = self.rfile.read(n) if n > 0 else b""
        except (socket.timeout, OSError):
            self.close_connection = True       # 读超时/断开：没法回话，直接关
            return
        src = None
        for enc in ("utf-8", "gbk"):        # 桌宠发 \uXXXX 转义(纯 ASCII)；gbk 是给手搓请求兜底
            try:
                src = json.loads(raw.decode(enc))
                break
            except (UnicodeDecodeError, ValueError):
                continue
        if not isinstance(src, dict):
            self._send_json(400, {"error": {"message": "请求体不是合法 JSON（需 UTF-8 或 GBK）"}})
            return

        stream = bool(src.get("stream"))
        payload, added_tools = prepare_payload(src, p.aliases)
        requested = str(src.get("model") or "")
        model = str(payload.get("model") or "")
        t0 = time.time()

        result = p.attempt(payload, stream)
        fallback_used = False
        if result[0] == "error" and result[2] in ("model", "gate") and model != p.fallback_model:
            p.log(f"模型 {model} 被拒（{result[2]}: {result[3][:80]}），回退到 {p.fallback_model}")
            payload["model"] = p.fallback_model
            model = p.fallback_model
            fallback_used = True
            result = p.attempt(payload, stream)

        tag = f"{requested or model}" + (f"→{model}" if model != requested else "")
        extra = f" 补工具×{added_tools}" if added_tools else ""
        if fallback_used:
            extra += " [回退]"

        kind = result[0]
        if kind == "sse":
            resp, first = result[1], result[2]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            sent = 0
            ok = True
            try:
                buf = first
                while buf:
                    self._write_chunk(buf)
                    sent += len(buf)
                    buf = (getattr(resp, "read1", None) or resp.read)(65536)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                ok = False
                p.log(f"{tag} 客户端断开，中止转发")
            except Exception as e:
                ok = False
                p.log(f"{tag} 转发中断: {type(e).__name__}: {e}")
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
                if ok:
                    try:
                        self.wfile.write(b"0\r\n\r\n")
                    except OSError:
                        pass
            if ok:
                p.log(f"{tag} 流式 {sent}B {time.time() - t0:.1f}s{extra}")
            return

        if kind in ("json", "completion"):
            body = result[2]
            raw_out = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            try:
                obj = body if isinstance(body, dict) else json.loads(raw_out.decode("utf-8"))
                if not isinstance(obj, dict):
                    raise ValueError("顶层不是对象")
            except ValueError as e:
                # 上游回了非 JSON（HTML 错误页 / 截断等）：明确 502，别让异常把连接直接掐掉
                self._send_json(502, {"error": {"message": f"上游返回无法解析：{e}",
                                                "type": "bad_upstream"}})
                p.log(f"{tag} 上游响应非 JSON：{raw_out[:120]!r}")
                return
            if stream:
                self._send_sse_single(obj)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw_out)))
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.wfile.write(raw_out)
                except OSError:
                    pass
            p.log(f"{tag} {'流式(单帧)' if stream else '整包'} {len(raw_out)}B {time.time() - t0:.1f}s{extra}")
            return

        if kind == "error":
            status, ekind, detail = result[1], result[2], result[3]
            msg = friendly_message(ekind, model, detail)
            out = status if isinstance(status, int) and 400 <= status < 600 else 502
            if out in (401, 403):
                # 上游 401/403 是"模型不可路由 / 资格门"，不是本地 Key 错——
                # 原样透传会让客户端误报"API Key 无效"，统一映射为 502 并带分类 type
                out = 502
            self._send_json(out, {"error": {"message": msg, "type": ekind}})
            p.log(f"{tag} 错误 {status} {ekind}: {detail[:120]}")
            return

        # neterr
        self._send_json(502, {"error": {"message": f"连不上上游：{result[3]}", "type": "net"}})
        p.log(f"{tag} 网络错误: {result[3]}")

    # ------------------------------------------------------------ GET
    def do_GET(self):
        if not self._origin_ok():
            return
        p = self.proxy
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/health":
            self._send_json(200, {"ok": True, "fallback": p.fallback_model,
                                  "session": (p.session or "")[:20] + "…"})
            return
        if path in ("/v1/models", "/models"):
            try:
                req = urllib.request.Request(f"{UPSTREAM}/zen/v1/models",
                                             headers=p.upstream_headers(False))
                with _OPENER.open(req, timeout=60) as r:
                    data = json.loads(r.read().decode("utf-8"))
                ids = [m.get("id") for m in (data.get("data") or [])
                       if isinstance(m, dict) and isinstance(m.get("id"), str)
                       and "-free" in m["id"]]
                self._send_json(200, {"object": "list", "data": [
                    {"id": i, "object": "model", "owned_by": "opencode-free"} for i in ids]})
                p.log(f"模型清单：{len(ids)} 个免费模型")
            except Exception as e:
                self._send_json(502, {"error": {"message": f"取模型清单失败：{e}"}})
            return
        self._send_json(404, {"error": {"message": f"未知路径 {path}"}})


# ---------------------------------------------------------------- 独立运行
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="白嫖通道本地代理（OpenCode Zen 免费车道）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--fallback", default=DEFAULT_FALLBACK, help="被拒模型自动回退目标")
    ap.add_argument("--data-dir", default=None, help="日志/会话文件目录（默认脚本同目录）")
    ap.add_argument("--new-session", action="store_true", help="换一个新会话（额度按会话记）")
    args = ap.parse_args(argv)

    proxy = FreelaneProxy(data_dir=args.data_dir, fallback_model=args.fallback, port=args.port)
    port = proxy.start(preferred_port=args.port, new_session=args.new_session, allow_dynamic=False)
    if not port:
        return 1
    proxy.log(f"独立模式：其它工具可直接用 http://{proxy.host}:{port}/v1（Key 任意）")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        proxy.stop()
        proxy.log("代理关闭（Ctrl+C）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
