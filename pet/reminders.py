"""提醒调度：喝水提醒 + 日程监控。

ScheduleMonitor 每个日程每天最多提醒两次：提前 remind_before_min 一次、开始时刻一次。
"""
import datetime as dt
import random

from PySide6.QtCore import QObject, QTimer, Signal

WATER_LINES = [
    "主人～该喝水啦💧",
    "补充水分时间到！💧",
    "喝口水休息一下吧，我在看着你哦👀",
    "叮！今日饮水量进度 +1 杯💧",
]


class WaterReminder(QObject):
    fired = Signal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._cfg = config
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._fire)
        self._next_at: dt.datetime | None = None
        self.restart()

    def restart(self):
        w = self._cfg["water"]
        if w.get("enabled") and w.get("interval_min", 0) > 0:
            self._schedule_next(dt.datetime.now())
        else:
            self._timer.stop()
            self._next_at = None

    @staticmethod
    def in_active(hour: int, start: int, end: int) -> bool:
        """活跃时段判定：start < end 为当天区间；start > end 为跨夜（如 22→6）；相等 = 全天。"""
        if start == end:
            return True
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def _hours(self):
        w = self._cfg["water"]
        return int(w.get("active_start", 0)), int(w.get("active_end", 24))

    def _fire(self):
        now = dt.datetime.now()
        if self.in_active(now.hour, *self._hours()):
            self.fired.emit()
        self._schedule_next(now)

    def _schedule_next(self, now: dt.datetime):
        w = self._cfg["water"]
        interval = int(w.get("interval_min", 0))
        if interval <= 0 or not w.get("enabled"):
            self._timer.stop()
            self._next_at = None
            return
        candidate = now + dt.timedelta(minutes=interval)
        start, end = self._hours()
        if self.in_active(candidate.hour, start, end):
            self._next_at = candidate
        else:
            # 落在静默段：顺延到下一个活跃起点（今天或明天的 start 点）
            nxt = dt.datetime.combine(candidate.date(), dt.time(start % 24))
            if nxt <= candidate:
                nxt += dt.timedelta(days=1)
            self._next_at = nxt
        delay = max(1000, int((self._next_at - now).total_seconds() * 1000))
        self._timer.start(delay)

    def next_at(self) -> dt.datetime | None:
        """下次喝水提醒时间（未启用返回 None）。"""
        return self._next_at

    @staticmethod
    def random_line() -> str:
        return random.choice(WATER_LINES)


class ScheduleMonitor(QObject):
    upcoming = Signal(dict, int)   # (日程, 距开始分钟数)
    starting = Signal(dict)        # 开始时刻
    checked = Signal()

    POLL_MS = 20_000
    # 到点提醒的补发上限：轮询/卡顿延迟内照发；睡眠唤醒后已过去很久的开始时刻不再补发
    LATE_GRACE = dt.timedelta(minutes=5)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self._store = store
        self._notified: set[str] = set()
        self._last_check: dt.datetime | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self.check)
        self._timer.start()

    def check(self, now: dt.datetime | None = None):
        from .schedule_store import _interval
        now = now or dt.datetime.now()
        # 首次检查回看宽限窗口：程序在日程开始后短暂启动/恢复时仍能补发一次。
        last = self._last_check or (now - self.LATE_GRACE)
        if last > now:  # 系统时间被往回调：重置基准，避免永远不触发
            last = now - dt.timedelta(milliseconds=self.POLL_MS)
        self._last_check = now
        candidates = []
        # 昨天（跨午夜仍在进行）、今天、明天（00:xx 日程的提前提醒落在今天）
        for offset in (-1, 0, 1):
            day = now.date() + dt.timedelta(days=offset)
            for e in self._store.entries_for(day):
                try:
                    start, _end = _interval(e, day)
                except (ValueError, KeyError, AttributeError, TypeError):
                    continue
                candidates.append((start, e))
        for start, e in candidates:
            eid = e.get("id", e.get("title", "?"))
            # 去重键用"这次发生"的开始时刻，而不是检查当天：跨午夜不重复、不漏
            occ = start.strftime("%Y-%m-%dT%H:%M")
            try:
                before = int(e.get("remind_before_min", 5) or 0)
            except (TypeError, ValueError):
                before = 5
            left_seconds = (start - now).total_seconds()
            pre_key, start_key = f"{occ}:{eid}:pre", f"{occ}:{eid}:start"
            # -1（如学习块）：无"提前提醒"，但到点确认提醒照发（用户要求课程开始/结束都有确认）
            if before > 0 and 0 < left_seconds <= before * 60 and pre_key not in self._notified:
                self._notified.add(pre_key)
                self.upcoming.emit(e, max(1, int(left_seconds // 60)))
            elif (last < start <= now and now - start <= self.LATE_GRACE
                  and start_key not in self._notified):
                # 区间触发：上次检查到本次检查之间跨过了开始时刻
                self._notified.add(start_key)
                self.starting.emit(e)
        self._prune(now)
        self.checked.emit()

    def _prune(self, now: dt.datetime):
        """清掉两天前的去重键，防止常驻运行时集合无限增长。"""
        cutoff = (now - dt.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        self._notified = {k for k in self._notified if k[:16] >= cutoff}
