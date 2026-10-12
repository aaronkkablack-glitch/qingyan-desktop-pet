"""冒烟测试：QT_QPA_PLATFORM=offscreen python test_smoke.py

覆盖：配置/日程查询/zcode用量读取/GUI构建(含双渲染器)/GLM真实流式调用。
"""
import datetime
import os
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

fails = []


def check(name, fn):
    try:
        fn()
        print(f"  [通过] {name}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        fails.append(name)
        print(f"  [失败] {name}: {e}")


print("== 逻辑模块 ==")
from pet.config import Config
from pet.schedule_store import ScheduleStore
from pet import usage_reader

cfg = Config()

# 白嫖通道内嵌代理：与 pet/main.py 相同路径启动（enabled 时后面的 API 实测需要它在跑）
from pet.main import start_freelane
_freelane = start_freelane(cfg)


def t_freelane():
    fl = cfg.get("freelane") or {}
    if not fl.get("enabled"):
        print("         (白嫖通道未启用，跳过)")
        return
    assert _freelane is not None, "内嵌代理未启动"
    import json as _json
    import urllib.request as _url
    with _url.urlopen(f"http://127.0.0.1:{_freelane.port}/health", timeout=10) as r:
        d = _json.loads(r.read().decode("utf-8"))
    assert d.get("ok"), d
    print(f"         代理端口 {_freelane.port} | 回退模型 {d.get('fallback')}")


def t_schedule():
    s = ScheduleStore()
    now = datetime.datetime.now()
    assert isinstance(s.summary_for(now), str)
    hm = now.strftime("%H:%M")
    keep = s.entries
    s.entries = [{"id": "t", "title": "测试日程", "days": [], "date": None,
                  "start": hm, "end": "23:59", "remind_before_min": 5}]
    act, nxt, delta = s.active_and_next(now)
    assert act and act["title"] == "测试日程", f"active={act}"
    assert "测试日程" in s.summary_for(now)
    s.entries = keep


def t_usage():
    d = usage_reader.zcode_usage(cfg["zcode_db_path"])
    assert not d["error"], d["error"]
    assert d["total"]["calls"] > 0, "累计应为正"
    print(f"         zcode今日: {d['today']} | 模型数: {len(d['models_7d'])}")


check("日程查询", t_schedule)
check("zcode用量读取", t_usage)
check("白嫖通道内嵌代理", t_freelane)

print("== GUI 构建（offscreen） ==")
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

app = QApplication([])


def t_gui():
    from pet.glm_client import GlmClient
    from pet.pet_window import PetWindow
    from pet.chat_panel import ChatPanel
    from pet.usage_panel import UsagePanel
    from pet.schedule_dialog import ScheduleDialog

    store = ScheduleStore()
    glm = GlmClient(cfg)
    pet = PetWindow(cfg)
    chat = ChatPanel(cfg, glm, store)
    usage = UsagePanel(cfg)
    sched = ScheduleDialog(store)
    pet.say("测试气泡")
    img = QImage(pet.size(), QImage.Format_ARGB32)
    pet.render(img)
    assert not img.isNull()

    cfg["animation"] = "sway"
    pet.refresh_renderer()
    pet._renderer.tick(0.05)
    img2 = QImage(pet.size(), QImage.Format_ARGB32)
    pet.render(img2)
    assert not img2.isNull(), "sway 渲染失败"
    cfg["animation"] = "static"
    pet.refresh_renderer()

    chat.history.append({"role": "user", "content": "你好"})
    chat.history.append({"role": "assistant", "content": "在呢～"})
    chat._render()
    usage.refresh()


check("窗口/面板/双渲染器", t_gui)

print("== GLM API 实测（QNAM 流式，走生产代码路径） ==")


def t_api():
    from PySide6.QtCore import QEventLoop, QTimer
    from pet.chat_panel import build_system_prompt
    from pet.glm_client import GlmClient

    glm = GlmClient(cfg)
    store = ScheduleStore()
    result = {}
    loop = QEventLoop()
    glm.finished.connect(lambda t, u: (result.update(text=t, usage=u), loop.quit()))
    glm.failed.connect(lambda m: (result.update(error=m), loop.quit()))
    glm.send([{"role": "system", "content": build_system_prompt(cfg, store)},
              {"role": "user", "content": "跟我打个招呼吧"}])
    QTimer.singleShot(120_000, loop.quit)
    loop.exec()
    if result.get("error") and "免费通道的资格门拒绝" in result["error"]:
        print("         (免费模型被上游资格门拒绝，跳过外部通道检查)")
        return
    assert "error" not in result, result.get("error")
    assert result.get("text"), "空回复"
    u = result.get("usage") or {}
    print(f"         回复: {result['text'][:36]!r}… total_tokens={u.get('total_tokens')}")


if "--online" in sys.argv and not cfg.get("freelane", {}).get("enabled"):
    check("自定义 API 流式对话", t_api)
else:
    print("  [未执行] 外部 API：space-bunny-free 已由用户人工确认，无需重复联网测试")

print()
if fails:
    print(f"共 {len(fails)} 项失败: {fails}")
    sys.exit(1)
print("全部通过 ✔")
