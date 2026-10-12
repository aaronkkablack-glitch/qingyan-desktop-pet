"""通过真实 Qt 网络、本地 HTTP 服务测试多轮工具、取消和过时任务。"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from pet import chat_panel as cp
from pet.glm_client import GlmClient
app = QApplication.instance() or QApplication([])

class Cfg(dict):
    def save(self): pass
class Store:
    def summary_for(self, _now): return "无安排"

def test_two_tool_rounds_reach_final_assistant_response():
    bodies = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            bodies.append(body)
            idx = len(bodies)
            if idx <= 2:
                msg = {"content": "", "tool_calls": [{"id": str(idx), "type": "function",
                       "function": {"name": "list_apps", "arguments": "{}"}}]}
            else:
                msg = {"content": "已完成", "tool_calls": []}
            if body.get("stream"):
                raw = ('data: ' + json.dumps({"choices": [{"delta": msg}]}) + '\n\ndata: [DONE]\n\n').encode()
            else:
                raw = json.dumps({"choices": [{"message": msg}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if body.get("stream") else "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with tempfile.TemporaryDirectory() as tmp, patch.object(cp, "HISTORY_PATH", str(Path(tmp)/"h.json")):
        cfg = Cfg(api_key="test", api_base=f"http://127.0.0.1:{server.server_port}/v1",
                  chat_model="m", chat_models=["m"], thinking_effort="off", max_tokens=128)
        panel = cp.ChatPanel(cfg, GlmClient(cfg), Store())
        ended = []
        loop = QEventLoop()
        panel.turn_ended.connect(lambda result: (ended.append(result), loop.quit()))
        panel.toolhost.run = lambda *_: (True, "ok")
        panel.input.setPlainText("工具链")
        panel.send()
        cfg["api_base"] = "https://invalid.example"
        cfg["chat_model"] = "changed"
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(5000)
        loop.exec()
        timer.stop()
        assert ended == ["done"], panel.status.text()
        assert len(bodies) == 3 and all(b["model"] == "m" for b in bodies)
        assert panel.history[-1]["content"] == "已完成"
        assert not panel.busy
        # 在工具回传已排队但还没发送时停止，任务不得启动新网络请求。
        panel._busy = True
        panel._continue_nonstream()
        panel.stop_reply()
        app.processEvents()
        assert len(bodies) == 3 and ended[-1] == "cancelled"
        panel.shutdown()
        panel.close()
    server.shutdown()
    server.server_close()
    thread.join(1)

def test_cancel_active_nonstream_and_restart():
    started = threading.Event()
    release = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            started.set()
            release.wait(3)
            raw = b'{"choices":[{"message":{"content":"late"}}]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try: self.wfile.write(raw)
            except OSError: pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg = Cfg(api_key="test", api_base=f"http://127.0.0.1:{server.server_port}/v1", chat_model="m", thinking_effort="off")
    client = GlmClient(cfg)
    ended = []
    client.finished.connect(lambda *_: ended.append("finished"))
    client.failed.connect(lambda *_: ended.append("failed"))
    client.send([{"role":"user", "content":"test"}], stream=False, config=cfg)
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    def stop():
        if started.is_set():
            client.cancel(silent=True)
            release.set()
            loop.quit()
    timer.timeout.connect(stop)
    timer.start()
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(loop.quit)
    watchdog.start(3000)
    loop.exec()
    timer.stop()
    watchdog.stop()
    assert started.is_set() and not client.busy and not ended
    release.set()
    server.shutdown()
    server.server_close()
    app.processEvents()
    assert not ended

if __name__ == "__main__":
    test_two_tool_rounds_reach_final_assistant_response()
    test_cancel_active_nonstream_and_restart()
    print("Qt 本地工具链及取消测试通过")
