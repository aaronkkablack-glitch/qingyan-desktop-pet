"""ZcodeWatcher 事件解析测试：turn 边界驱动状态，工具/心跳事件不干扰。
运行: python -m pytest tests/test_zcode_watcher.py -q  或 QT_QPA_PLATFORM=offscreen python tests/test_zcode_watcher.py
"""
import json
import os
import shutil
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication

from pet.zcode_watcher import ZcodeWatcher

app = QCoreApplication.instance() or QCoreApplication([])

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_zcode_log")
LOG = os.path.join(TMP, "zcode-2026-10-04.jsonl")


def write(events, name=LOG, append=True):
    os.makedirs(os.path.dirname(name), exist_ok=True)
    with open(name, "a" if append else "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def ev(event, turn="t1"):
    return {"timestamp": "2026-10-04T10:00:00.000Z", "level": "info",
            "event": event, "turnId": turn}


NOISE = [{"event": "zcode_protocol.process.memory_sample"},
         {"event": "model.request.started", "turnId": "t1"},
         {"event": "tool.call.started", "turnId": "t1"},
         {"event": "tool.call.completed", "turnId": "t1"},
         {"event": "model.sdk.stream.completed", "turnId": "t1"},
         {"event": "model.request.completed", "turnId": "t1"}]


def make_watcher():
    w = ZcodeWatcher(TMP)
    got = []
    w.state_changed.connect(got.append)
    return w, got


def fresh():
    shutil.rmtree(TMP, ignore_errors=True)
    write([], append=False)


def test_turn_lifecycle_and_noise_immunity():
    """对话开始→思考一次；agent 循环噪音（模型请求/工具/心跳）不产生任何状态变化；
    对话结束→庆祝恰好一次。"""
    fresh()
    write([ev("turn.started")] + NOISE)
    w, got = make_watcher()
    w.start()          # 基线：已有未闭合 turn → 直接 thinking
    w._poll()          # 无新数据
    assert got == ["thinking"], got
    write(NOISE * 5)   # 工具循环、心跳再怎么刷都不动
    w._poll()
    assert got == ["thinking"], "噪音事件不得触发状态变化"
    write([ev("turn.completed")])
    w._poll()
    assert got == ["thinking", "done"], "对话结束应庆祝一次"
    write(NOISE)       # 结束后的心跳
    w._poll()
    assert got == ["thinking", "done"], "庆祝不得重复"


def test_partial_line_not_consumed():
    """正在写半行时不消费，等完整行再解析。"""
    fresh()
    write([ev("turn.started")])
    w, got = make_watcher()
    w.start()
    with open(LOG, "a", encoding="utf-8") as f:
        f.write('{"event": "turn.comp')   # 无换行的半行
    w._poll()
    assert got == ["thinking"], "半行不得被解析"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write('leted", "turnId": "t1"}\n')
    w._poll()
    assert got == ["thinking", "done"]


def test_parallel_turns_celebrate_once_all_done():
    """并发对话：一个完成不打断另一个的思考，全部结束才庆祝一次。"""
    fresh()
    write([ev("turn.started", "a")])
    w, got = make_watcher()
    w.start()
    write([ev("turn.started", "b")])
    w._poll()
    assert got == ["thinking"], "第二个 turn 开始不重复触发"
    write([ev("turn.completed", "a")])
    w._poll()
    assert got == ["thinking"], "还有对话在进行，不得庆祝"
    write([ev("turn.completed", "b")])
    w._poll()
    assert got == ["thinking", "done"], "全部结束庆祝一次"


def test_turn_failed_emits_error():
    fresh()
    write([ev("turn.started")])
    w, got = make_watcher()
    w.start()
    write([ev("turn.failed")])
    w._poll()
    assert got == ["thinking", "error"], got


def test_day_rollover_restarts_offset():
    """跨天新文件从 offset=0 重新消费。"""
    fresh()
    write([ev("turn.started"), ev("turn.completed")])
    w, got = make_watcher()
    w.start()
    assert got == []  # 基线只报未闭合 turn
    new_log = os.path.join(TMP, "zcode-2026-10-05.jsonl")
    write([ev("turn.started")], name=new_log)
    w._poll()
    assert got == ["thinking"], "新一天的 turn 应被读到"


def test_baseline_closed_history_is_idle():
    """历史 turn 全部闭合 → 启动基线不触发任何状态。"""
    fresh()
    write([ev("turn.started"), ev("turn.completed")] * 3)
    w, got = make_watcher()
    w.start()
    assert got == []


if __name__ == "__main__":
    test_turn_lifecycle_and_noise_immunity()
    test_partial_line_not_consumed()
    test_parallel_turns_celebrate_once_all_done()
    test_turn_failed_emits_error()
    test_day_rollover_restarts_offset()
    test_baseline_closed_history_is_idle()
    shutil.rmtree(TMP, ignore_errors=True)
    print("ZcodeWatcher 事件解析测试通过 ✔")
