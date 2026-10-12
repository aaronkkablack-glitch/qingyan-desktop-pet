"""第二轮时间模型测试：跨午夜日程、秒级提醒和喝水有效时间。"""
import datetime as dt
import os
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication

from pet.schedule_store import ScheduleStore
from pet.reminders import ScheduleMonitor, WaterReminder

app = QCoreApplication.instance() or QCoreApplication([])


class _Cfg(dict):
    pass


def test_cross_midnight_schedule_is_active_and_next_is_precise():
    store = ScheduleStore.__new__(ScheduleStore)
    store.entries = [{"id": "night", "title": "夜间任务", "days": [], "date": None,
                      "start": "22:00", "end": "02:00", "remind_before_min": 5}]
    active, nxt, delta = store.active_and_next(dt.datetime(2026, 10, 11, 1, 30, 45))
    assert active and active["id"] == "night"
    assert nxt and nxt["id"] == "night" and delta == 1229


def test_schedule_monitor_uses_seconds_for_pre_and_start():
    store = ScheduleStore.__new__(ScheduleStore)
    store.entries = [{"id": "lesson", "title": "课程", "days": [], "date": None,
                      "start": "10:00", "end": "11:00", "remind_before_min": 5}]
    monitor = ScheduleMonitor(store)
    upcoming, starting = [], []
    monitor.upcoming.connect(lambda entry, left: upcoming.append((entry["id"], left)))
    monitor.starting.connect(lambda entry: starting.append(entry["id"]))
    monitor.check(dt.datetime(2026, 10, 11, 9, 54, 59))
    assert upcoming == []
    monitor.check(dt.datetime(2026, 10, 11, 9, 55, 1))
    assert upcoming == [("lesson", 4)]
    monitor.check(dt.datetime(2026, 10, 11, 10, 0, 1))
    assert starting == ["lesson"]


def test_water_next_at_skips_inactive_hours():
    w = WaterReminder(_Cfg(water={"enabled": True, "interval_min": 20,
                                  "active_start": 9, "active_end": 22}))
    w._schedule_next(dt.datetime(2026, 10, 11, 21, 55))
    assert w.next_at() == dt.datetime(2026, 10, 12, 9, 0)
    w._schedule_next(dt.datetime(2026, 10, 11, 8, 50))
    assert w.next_at() == dt.datetime(2026, 10, 11, 9, 10)


if __name__ == "__main__":
    test_cross_midnight_schedule_is_active_and_next_is_precise()
    test_schedule_monitor_uses_seconds_for_pre_and_start()
    test_water_next_at_skips_inactive_hours()
    print("第二轮日程与时间测试通过 ✔")
