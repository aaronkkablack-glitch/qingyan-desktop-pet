"""第五轮-第一轮回归：到点提醒区间触发、午夜提前提醒、跨夜喝水、凭据快照加密、损坏文件保护。"""
import datetime as dt
import json
import os
import sys
import tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication

from pet import config as cfgmod
from pet import schedule_store as ssmod
from pet import usage_reader as umod
from pet.reminders import ScheduleMonitor, WaterReminder
from pet.schedule_store import ScheduleStore, valid_hm

app = QCoreApplication.instance() or QCoreApplication([])


def _store(entries):
    s = ScheduleStore.__new__(ScheduleStore)
    s.entries = entries
    s._no_save = False
    return s


def _monitor(entries):
    m = ScheduleMonitor(_store(entries))
    m._timer.stop()
    got = {"pre": [], "start": []}
    m.upcoming.connect(lambda e, left: got["pre"].append((e["id"], left)))
    m.starting.connect(lambda e: got["start"].append(e["id"]))
    return m, got


def test_start_fires_with_20s_polling_at_any_phase():
    """P0：20 秒轮询任意相位都必须命中到点提醒，且只发一次。"""
    for phase in range(0, 20):
        m, got = _monitor([{"id": "blk", "title": "学习块", "days": [], "date": None,
                            "start": "10:00", "end": "11:00", "remind_before_min": -1}])
        t = dt.datetime(2026, 10, 11, 9, 59, 0) + dt.timedelta(seconds=phase)
        for _ in range(12):
            m.check(t)
            t += dt.timedelta(seconds=20)
        assert got["start"] == ["blk"], (phase, got)
        assert got["pre"] == []


def test_wake_from_sleep_does_not_replay_stale_start():
    m, got = _monitor([{"id": "a", "title": "A", "days": [], "date": None,
                        "start": "10:00", "end": "11:00", "remind_before_min": 0}])
    m.check(dt.datetime(2026, 10, 11, 9, 0, 0))
    m.check(dt.datetime(2026, 10, 11, 10, 30, 0))   # 睡眠 90 分钟后唤醒
    assert got["start"] == []
    m2, got2 = _monitor([{"id": "a", "title": "A", "days": [], "date": None,
                          "start": "10:00", "end": "11:00", "remind_before_min": 0}])
    m2.check(dt.datetime(2026, 10, 11, 9, 58, 0))
    m2.check(dt.datetime(2026, 10, 11, 10, 3, 0))   # 卡顿 5 分钟内：照发
    assert got2["start"] == ["a"]


def test_first_check_replays_recent_start_only():
    """首次启动检查：开始后 5 分钟内补发，超过宽限不补发。"""
    m, got = _monitor([{"id": "recent", "title": "最近", "days": [], "date": None,
                        "start": "10:00", "end": "11:00", "remind_before_min": 0}])
    m.check(dt.datetime(2026, 10, 11, 10, 3))
    assert got["start"] == ["recent"]
    m2, got2 = _monitor([{"id": "stale", "title": "过期", "days": [], "date": None,
                          "start": "10:00", "end": "11:00", "remind_before_min": 0}])
    m2.check(dt.datetime(2026, 10, 11, 10, 6))
    assert got2["start"] == []


def test_pre_reminder_before_midnight_entry():
    m, got = _monitor([{"id": "mid", "title": "零点任务", "days": [], "date": None,
                        "start": "00:02", "end": "01:00", "remind_before_min": 5}])
    m.check(dt.datetime(2026, 10, 11, 23, 58, 0))
    assert got["pre"] == [("mid", 4)], got
    m.check(dt.datetime(2026, 10, 12, 0, 0, 10))     # 过了午夜不重复提前提醒
    assert got["pre"] == [("mid", 4)]
    m.check(dt.datetime(2026, 10, 12, 0, 2, 5))
    assert got["start"] == ["mid"]


def test_notified_set_is_pruned():
    m, _ = _monitor([{"id": "a", "title": "A", "days": [], "date": None,
                      "start": "10:00", "end": "11:00", "remind_before_min": 0}])
    t = dt.datetime(2026, 10, 1, 9, 59, 50)
    for _ in range(10):
        m.check(t)
        m.check(t + dt.timedelta(seconds=20))
        t += dt.timedelta(days=1)
    assert len(m._notified) <= 3, m._notified


def test_water_cross_night_and_24():
    assert WaterReminder.in_active(23, 22, 6) and WaterReminder.in_active(3, 22, 6)
    assert not WaterReminder.in_active(12, 22, 6)
    assert WaterReminder.in_active(23, 9, 24) and not WaterReminder.in_active(8, 9, 24)
    w = WaterReminder({"water": {"enabled": True, "interval_min": 30,
                                 "active_start": 22, "active_end": 6}})
    w._schedule_next(dt.datetime(2026, 10, 11, 23, 0))
    assert w.next_at() == dt.datetime(2026, 10, 11, 23, 30)
    w._schedule_next(dt.datetime(2026, 10, 12, 5, 45))
    assert w.next_at() == dt.datetime(2026, 10, 12, 22, 0)
    w._timer.stop()


def test_valid_hm():
    assert valid_hm("09:30") and valid_hm("23:59") and valid_hm("0:05")
    for bad in ("9点", "25:00", "09:00:00", "9:5", "", "ab:cd"):
        assert not valid_hm(bad), bad


def _with_config_path(fn):
    old = cfgmod.CONFIG_PATH
    cfgmod.CONFIG_PATH = os.path.join(tempfile.mkdtemp(), "config.json")
    try:
        fn(cfgmod.CONFIG_PATH)
    finally:
        cfgmod.CONFIG_PATH = old


def test_freelane_custom_key_encrypted():
    def body(path):
        cfg = cfgmod.Config()
        cfg["api_key"] = "freelane"
        cfg["freelane"]["custom"] = {"api_base": "https://x", "api_key": "snap-secret-123"}
        cfg.save()
        text = open(path, encoding="utf-8").read()
        cfg2 = cfgmod.Config()
        if os.name == "nt":
            assert "snap-secret-123" not in text
            assert cfg2["freelane"]["custom"]["api_key"] == "snap-secret-123"
            assert "api_key_protected" not in cfg2["freelane"]["custom"]
    _with_config_path(body)


def test_corrupt_config_backed_up_and_bad_values_dont_block_save():
    def body(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ broken json")
        cfg = cfgmod.Config()
        bak = [n for n in os.listdir(os.path.dirname(path)) if ".corrupt-" in n]
        assert bak, "损坏配置应被备份"
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"max_tokens": "abc", "water": "oops"}, f)
        cfg = cfgmod.Config()
        assert cfg["max_tokens"] == 2048 and cfg["water"]["interval_min"] == 45
        cfg.save()  # 不应抛异常
    _with_config_path(body)


def test_deexpand_requires_separator():
    home = os.path.expanduser("~").replace("\\", "/").rstrip("/")
    d = cfgmod._deexpand({"zcode_log_dir": home + "avier/log", "zcode_db_path": home + "/db"})
    assert d["zcode_log_dir"] == home + "avier/log"
    assert d["zcode_db_path"] == "~/db"


def test_corrupt_schedule_and_usage_backed_up():
    tmp = tempfile.mkdtemp()
    old_s, old_u = ssmod.SCHEDULE_PATH, umod.PET_USAGE_PATH
    ssmod.SCHEDULE_PATH = os.path.join(tmp, "schedule.json")
    umod.PET_USAGE_PATH = os.path.join(tmp, "pet_usage.json")
    try:
        for p in (ssmod.SCHEDULE_PATH, umod.PET_USAGE_PATH):
            with open(p, "w", encoding="utf-8") as f:
                f.write("not json")
        s = ScheduleStore()
        assert s.entries == []
        umod.record_pet_usage("m", {"prompt_tokens": 1, "completion_tokens": 2})
        names = os.listdir(tmp)
        assert any(n.startswith("schedule.json.corrupt-") for n in names), names
        assert any(n.startswith("pet_usage.json.corrupt-") for n in names), names
        assert json.load(open(umod.PET_USAGE_PATH, encoding="utf-8"))["by_date"]
    finally:
        ssmod.SCHEDULE_PATH, umod.PET_USAGE_PATH = old_s, old_u


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("第五轮-第一轮回归测试通过 ✔")
