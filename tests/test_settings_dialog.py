"""接口设置对话框测试：保存写回 config、新模型追加、thinking off 不发字段。
运行: python -m pytest tests/test_settings_dialog.py -q  或 QT_QPA_PLATFORM=offscreen python tests/test_settings_dialog.py
"""
import json
import os
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.glm_client import GlmClient
from pet.settings_dialog import SettingsDialog

app = QApplication.instance() or QApplication([])


def test_save_writes_config_and_app_aliases(tmp_cfg=None):
    """填写→保存：cfg 各字段更新；自定义模型名追加进 chat_models；应用别名表写入。"""
    import copy, tempfile
    from pet import config as cfgmod
    # 用临时 CONFIG_PATH，不污染真实 config.json
    tmpdir = tempfile.mkdtemp()
    cfgmod.CONFIG_PATH = os.path.join(tmpdir, "config.json")
    cfg = Config()
    cfg["app_aliases"] = {"网易云": r"C:\Program Files\CloudMusic\cloudmusic.exe"}
    dlg = SettingsDialog(cfg)
    assert dlg.alias_table.rowCount() == 1, "已有别名应预填进表格"
    dlg.key_edit.setText("test.key123")
    dlg.base_edit.setText("https://api.deepseek.com/v1/")
    dlg.model_combo.setCurrentText("deepseek-chat")
    dlg.effort_combo.setCurrentText("off")
    dlg.tokens_spin.setValue(4096)
    dlg._append_alias_row("B站", "https://www.bilibili.com")
    dlg._append_alias_row("", "只有目标没别名应被忽略")  # 半行 → 收集时丢弃
    dlg._save()
    assert cfg["api_key"] == "test.key123"
    assert cfg["api_base"] == "https://api.deepseek.com/v1"  # 去尾斜杠
    assert cfg["chat_model"] == "deepseek-chat"
    assert "deepseek-chat" in cfg["chat_models"]
    assert cfg["thinking_effort"] == "off"
    assert cfg["max_tokens"] == 4096
    assert cfg["app_aliases"] == {"网易云": r"C:\Program Files\CloudMusic\cloudmusic.exe",
                                  "B站": "https://www.bilibili.com"}
    assert os.path.exists(cfgmod.CONFIG_PATH), "保存应写盘"


def test_build_body_thinking_off():
    """effort=off 时请求体不含 thinking 字段；low 时含。"""
    import copy
    from pet.config import DEFAULTS
    from PySide6.QtCore import QCoreApplication
    _app = QCoreApplication.instance() or QCoreApplication([])
    data = copy.deepcopy(DEFAULTS)
    data["thinking_effort"] = "off"

    class C:  # 最小 Config 替身
        def get(self, k, d=None):
            return data.get(k, d)
        def __getitem__(self, k):
            return data[k]

    c = GlmClient(C())
    body = c._build_body([{"role": "user", "content": "hi"}], "m", None, True)
    assert "thinking" not in body, "off 档不得发送 thinking 字段"
    data["thinking_effort"] = "low"
    body = c._build_body([{"role": "user", "content": "hi"}], "m", None, True)
    assert body.get("thinking") == {"type": "enabled", "effort": "low"}


def test_render_dirty_check():
    """聊天渲染脏检查：内容没变不重建文档（修滚动条被吸回顶端的根因）。"""
    from PySide6.QtCore import QObject, Signal
    from pet.chat_panel import ChatPanel

    class _Cfg(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)
        def save(self):
            pass

    class _Glm(QObject):
        thinking_started = Signal()
        chunk = Signal(str)
        finished = Signal(str, dict)
        failed = Signal(str)
        tool_calls_finished = Signal(list)

    cfg = _Cfg(api_key="", api_base="x", chat_models=["m"], chat_model="m",
               max_history_messages=20, app_aliases={})
    panel = ChatPanel(cfg, _Glm(), None)
    calls = {"n": 0}
    orig = panel.browser.setHtml

    def counting(html):
        calls["n"] += 1
        orig(html)

    panel.browser.setHtml = counting
    panel._render()                    # 首次（构造时已渲染过，_last_html 已有 → 不重设）
    n_after_first = calls["n"]
    panel._render()                    # 内容没变 → 不得 setHtml
    panel._render()
    assert calls["n"] == n_after_first, "内容未变化时不得重建文档（会重置滚动条）"
    panel.history.append({"role": "user", "content": "hi", "_t": "11:11"})
    panel._render()                    # 内容变了 → 重建一次
    assert calls["n"] == n_after_first + 1


def test_im_layout_and_strip_meta():
    """IM 布局：消息渲染带头像；API 上下文保留普通消息的发生时间。"""
    from PySide6.QtCore import QObject, Signal
    from pet.chat_panel import ChatPanel, AVATAR_PET, avatar_user

    class _Cfg(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)
        def save(self):
            pass

    class _Glm(QObject):
        thinking_started = Signal()
        chunk = Signal(str)
        finished = Signal(str, dict)
        failed = Signal(str)
        tool_calls_finished = Signal(list)

    cfg = _Cfg(api_key="", api_base="x", chat_models=["m"], chat_model="m",
               max_history_messages=20, app_aliases={})
    panel = ChatPanel(cfg, _Glm(), None)
    panel.history.append({"role": "user", "content": "你好", "_t": "09:01"})
    panel.history.append({"role": "assistant", "content": "在呢~", "_t": "09:01"})
    h = panel._build_html()
    assert avatar_user() in h and AVATAR_PET in h, "双方头像都应渲染"
    assert "09:01" in h, "时间戳应渲染"
    assert "·" in h

    m = panel._strip_meta({"role": "user", "content": "hi", "_t": "09:01"})
    assert m == {"role": "user", "content": "[这条消息发送于 09:01]\nhi"}, "旧记录时间也应进入上下文"
    m_full = panel._strip_meta({"role": "assistant", "content": "ok",
                                 "_t": "09:01", "_ts": "2026-10-11T09:01:22+08:00"})
    assert "2026-10-11T09:01:22+08:00" in m_full["content"]
    m2 = panel._strip_meta({"role": "tool", "tool_call_id": "t1",
                            "content": "ok", "_t": "09:01"})
    assert m2["content"] == "ok", "工具结果不得插入自然语言时间前缀"
    assert m2 == {"role": "tool", "tool_call_id": "t1", "content": "ok"}
    m3 = panel._strip_meta({"role": "assistant", "content": "",
                            "tool_calls": [{"id": "a"}], "_t": "09:01"})
    assert m3 == {"role": "assistant", "content": "", "tool_calls": [{"id": "a"}]}, "工具调用消息协议不得改变"


def test_chat_time_context():
    """系统提示词声明当前真实时间优先，历史消息带发生时间。"""
    from pet.chat_panel import build_system_prompt

    class _Cfg(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)

    class _Store:
        def summary_for(self, now):
            return "无安排"

    prompt = build_system_prompt(_Cfg(system_prompt="人设"), _Store())
    assert "当前真实时间：" in prompt
    assert "唯一有效的现在" in prompt


def test_water_next_at():
    """喝水提醒下次时间：enabled 时 next_at ≈ now+interval；关闭时 None。"""
    from PySide6.QtCore import QCoreApplication
    _app = QCoreApplication.instance() or QCoreApplication([])
    import datetime as dt
    from pet.reminders import WaterReminder

    class _Cfg(dict):
        def __init__(self, w):
            super().__init__(water=w)
        def get(self, k, d=None):
            return dict.get(self, k, d)

    w = WaterReminder(_Cfg({"enabled": True, "interval_min": 20, "active_start": 9, "active_end": 22}))
    for hour, minute in ((12, 0), (21, 0), (21, 39), (21, 40), (23, 0), (8, 0)):
        now = dt.datetime(2026, 10, 11, hour, minute)
        w._schedule_next(now)
        candidate = now + dt.timedelta(minutes=20)
        expected = candidate if 9 <= candidate.hour < 22 else dt.datetime.combine(
            candidate.date() + dt.timedelta(days=int(candidate.hour >= 22)), dt.time(9))
        assert w.next_at() == expected
    w2 = WaterReminder(_Cfg({"enabled": False, "interval_min": 20}))
    assert w2.next_at() is None


def test_chat_history_persistence():
    """聊天记录持久化：落盘只存普通消息；重启加载恢复；清空删文件。"""
    import tempfile
    from PySide6.QtCore import QObject, Signal
    from pet import chat_panel as cp
    from pet.chat_panel import ChatPanel

    class _Cfg(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)
        def save(self):
            pass

    class _Glm(QObject):
        thinking_started = Signal(); chunk = Signal(str)
        finished = Signal(str, dict); failed = Signal(str)
        tool_calls_finished = Signal(list)

    tmpdir = tempfile.mkdtemp()
    old_path = cp.HISTORY_PATH
    cp.HISTORY_PATH = os.path.join(tmpdir, "chat_history.json")
    try:
        cfg = _Cfg(api_key="", api_base="x", chat_models=["m"], chat_model="m",
                   max_history_messages=20, app_aliases={})
        panel = ChatPanel(cfg, _Glm(), None)
        panel.history.append({"role": "user", "content": "早", "_t": "08:00"})
        panel.history.append({"role": "assistant", "content": "", "tool_calls": [{"id": "x"}],
                               "_t": "08:00"})
        panel.history.append({"role": "tool", "tool_call_id": "x", "content": "ok", "_t": "08:00"})
        panel.history.append({"role": "assistant", "content": "早上好", "_t": "08:00"})
        panel._persist_history()
        assert os.path.exists(cp.HISTORY_PATH)
        # 新面板（模拟重启）加载：tool 链不恢复，普通消息保留
        panel2 = ChatPanel(cfg, _Glm(), None)
        assert [m["content"] for m in panel2.history] == ["早", "早上好"]
        panel2.clear_history()
        assert not os.path.exists(cp.HISTORY_PATH)
        panel3 = ChatPanel(cfg, _Glm(), None)
        assert panel3.history == []
    finally:
        cp.HISTORY_PATH = old_path


def test_schedule_dialog_preserves_schedule_identity_and_rules():
    """保存日程时保留已有 id/days/date，新行才生成新 id。"""
    from pet.schedule_dialog import ScheduleDialog

    class Store:
        entries = [{"id": "keep-me", "title": "周期课", "plan": "练习",
                    "days": [0, 2], "date": None, "start": "09:00", "end": "10:00",
                    "remind_before_min": 5}]
        def save(self):
            pass

    dlg = ScheduleDialog(Store())
    dlg._save = dlg._save
    # 直接检查加载到行首 item 的元数据，避免弹出保存消息框。
    meta = dlg.table.item(0, 0).data(0x0100)
    assert meta["id"] == "keep-me"
    assert meta["days"] == [0, 2]

    dlg.store.entries = [{"id": "once", "title": "一次性", "plan": "",
                          "days": [], "date": "2026-10-20", "start": "11:00", "end": "12:00",
                          "remind_before_min": 0}]
    dlg.load()
    meta = dlg.table.item(0, 0).data(0x0100)
    assert meta["id"] == "once" and meta["date"] == "2026-10-20"
def test_pet_settings_dialog():
    """独立桌宠设置窗：保存写 water 配置 + 注册表自启（还原原状）。"""
    import tempfile
    from pet import config as cfgmod
    from pet import autostart
    from pet.pet_settings import PetSettingsDialog

    tmpdir = tempfile.mkdtemp()
    cfgmod.CONFIG_PATH = os.path.join(tmpdir, "config.json")
    cfg = Config()
    was = autostart.is_enabled()
    try:
        dlg = PetSettingsDialog(cfg)
        dlg.water_check.setChecked(True)
        dlg.water_interval.setValue(30)
        dlg.water_start.setValue(8)
        dlg.water_end.setValue(23)
        dlg.autostart_check.setChecked(True)
        dlg._save()
        assert cfg["water"]["enabled"] is True
        assert cfg["water"]["interval_min"] == 30
        assert cfg["water"]["active_start"] == 8 and cfg["water"]["active_end"] == 23
        assert autostart.is_enabled(), "保存应写注册表自启"
    finally:
        autostart.set_enabled(was)




def test_pet_height_slider():
    """桌宠大小滑块：实时预览改 cfg 与窗口尺寸；取消还原；保存落盘。"""
    import tempfile
    from pet import config as cfgmod
    from pet.pet_window import PetWindow
    from pet.pet_settings import PetSettingsDialog

    tmpdir = tempfile.mkdtemp()
    cfgmod.CONFIG_PATH = os.path.join(tmpdir, "config.json")
    cfg = Config()
    pet = PetWindow(cfg)
    h0 = pet.height()
    dlg = PetSettingsDialog(cfg, pet)
    dlg.height_slider.setValue(600)
    assert cfg["pet_height"] == 600
    assert pet.height() > h0, "拖动滑块应实时改变窗口尺寸"
    dlg.reject()
    assert cfg["pet_height"] == dlg._height_orig and pet.height() == h0, "取消应还原"
    dlg2 = PetSettingsDialog(cfg, pet)
    dlg2.height_slider.setValue(500)
    dlg2._save()
    saved = json.load(open(cfgmod.CONFIG_PATH, encoding="utf-8"))
    assert saved.get("pet_height") == 500, "保存应落盘"




def test_config_deexpand_home_paths():
    """分享加固：config 落盘时家目录路径反展开成 ~/ 形式（换机器跟随本机用户）。"""
    import tempfile
    from pet import config as cfgmod
    tmpdir = tempfile.mkdtemp()
    cfgmod.CONFIG_PATH = os.path.join(tmpdir, "config.json")
    cfg = Config()
    home = cfgmod.os.path.expanduser("~")
    cfg["zcode_log_dir"] = home + "/.zcode/cli/log"          # 模拟已固化的绝对路径
    cfg["zcode_db_path"] = home.replace("/", "\\") + "/.zcode/cli/db/db.sqlite"
    cfg["api_key"] = "k"
    cfg.save()
    raw = json.load(open(cfgmod.CONFIG_PATH, encoding="utf-8"))
    assert raw["zcode_log_dir"] == "~/.zcode/cli/log", raw["zcode_log_dir"]
    assert raw["zcode_db_path"] == "~/.zcode/cli/db/db.sqlite", raw["zcode_db_path"]
    assert cfg["api_key"] == "k"                              # 运行态仍保留 Key
    if os.name == "nt":
        assert raw.get("api_key", "") != "k"                 # Windows 不明文落盘
    # 重新加载：~/ 应展开回本机有效路径
    cfg2 = Config()
    assert cfg2["zcode_log_dir"].lower().startswith(home.lower())


if __name__ == "__main__":
    test_save_writes_config_and_app_aliases()
    test_build_body_thinking_off()
    test_render_dirty_check()
    test_im_layout_and_strip_meta()
    test_water_next_at()
    test_chat_history_persistence()
    test_schedule_dialog_preserves_schedule_identity_and_rules()
    test_pet_settings_dialog()
    test_pet_height_slider()
    test_config_deexpand_home_paths()
    print("接口设置+IM+喝水+聊天记录+桌宠设置测试通过 ✔")
