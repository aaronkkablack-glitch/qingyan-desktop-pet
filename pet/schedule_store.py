"""日程存储与查询。data/schedule.json：

{"entries": [{"id", "title", "days":[0-6] 或 "date":"2026-10-05",
              "start":"HH:MM", "end":"HH:MM", "remind_before_min":5, "note":""}]}
days: 0=周一 … 6=周日；days 与 date 二选一（都给则都命中）。
"""
import copy
import datetime as dt
import json
import os
import uuid

from .config import SCHEDULE_PATH, backup_corrupt

WEEK_CN = "一二三四五六日"

DEFAULT_SCHEDULE = {
    "entries": [
        {"id": "demo-1", "title": "示例：午休（可删）", "days": [0, 1, 2, 3, 4],
         "start": "12:00", "end": "13:30", "remind_before_min": 5, "note": "双击桌宠可和我聊日程"},
        {"id": "demo-2", "title": "示例：晚间复盘（可删）", "days": [1, 3],
         "start": "20:00", "end": "21:00", "remind_before_min": 10, "note": ""},
    ]
}


def _parse_hm(s: str):
    h, m = s.split(":")
    return int(h), int(m)


def valid_hm(s: str) -> bool:
    """严格 HH:MM（0-23 / 0-59）；'9点'、'25:00'、'09:00:00' 都不算。"""
    try:
        h, m = _parse_hm(s)
        dt.time(h, m)
        return len(s.split(":")[1]) == 2
    except (ValueError, AttributeError, TypeError):
        return False


def _interval(entry: dict, day: dt.date):
    """返回该日程在 day 开始的 [start, end) 本地时间区间。"""
    sh, sm = _parse_hm(entry["start"])
    eh, em = _parse_hm(entry["end"])
    start = dt.datetime.combine(day, dt.time(sh, sm))
    end_day = day + dt.timedelta(days=1) if (eh, em) <= (sh, sm) else day
    end = dt.datetime.combine(end_day, dt.time(eh, em))
    return start, end


class ScheduleStore:
    def __init__(self):
        self.entries: list[dict] = []
        self.load()

    def load(self):
        self._no_save = False
        if os.path.exists(SCHEDULE_PATH):
            try:
                with open(SCHEDULE_PATH, encoding="utf-8") as f:
                    entries = json.load(f).get("entries", [])
                if not isinstance(entries, list):
                    raise ValueError("entries 不是列表")
                for entry in entries:
                    if not isinstance(entry, dict) or not isinstance(entry.get("title"), str) \
                            or not valid_hm(entry.get("start")) or not valid_hm(entry.get("end")):
                        raise ValueError("日程条目或时间格式无效")
                    days = entry.get("days") or []
                    if not isinstance(days, list) or any(type(day) is not int or not 0 <= day <= 6 for day in days):
                        raise ValueError("星期字段无效")
                    if entry.get("date"):
                        dt.date.fromisoformat(entry["date"])
                    int(entry.get("remind_before_min", 5))
                self.entries = entries
            except OSError as e:
                # 读不了（被占用）：本次运行不回写，免得空列表覆盖用户日程
                print(f"[schedule] 读取失败，本次不回写: {e}")
                self.entries = []
                self._no_save = True
            except (ValueError, AttributeError, TypeError) as e:
                bak = backup_corrupt(SCHEDULE_PATH)
                if bak is None:
                    self._no_save = True
                print(f"[schedule] 日程文件损坏，已备份到 {bak}: {e}")
                self.entries = []
        else:
            self.entries = copy.deepcopy(DEFAULT_SCHEDULE["entries"])
            self.save()

    def save(self, entries: list[dict] | None = None):
        """落盘；传入 entries 时先写盘成功再替换内存，保证失败时两边一致。"""
        if getattr(self, "_no_save", False):
            raise OSError("启动时日程文件读取失败，为保护原文件已禁止保存，请重启后再试")
        data = self.entries if entries is None else entries
        os.makedirs(os.path.dirname(SCHEDULE_PATH), exist_ok=True)
        tmp = SCHEDULE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"entries": data}, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, SCHEDULE_PATH)
        self.entries = data

    def add(self, title, days=None, date=None, start="09:00", end="10:00",
            remind_before_min=5, note=""):
        entries = self.entries + [{
            "id": uuid.uuid4().hex[:8], "title": title,
            "days": days or [], "date": date, "start": start, "end": end,
            "remind_before_min": int(remind_before_min), "note": note,
        }]
        self.save(entries)

    def remove(self, entry_id):
        self.save([e for e in self.entries if e.get("id") != entry_id])

    def entries_for(self, day: dt.date) -> list[dict]:
        wd = day.weekday()
        out = []
        for e in self.entries:
            hit = False
            days = e.get("days") or []
            if days and wd in days:
                hit = True
            if e.get("date") == day.isoformat():
                hit = True
            if not days and not e.get("date"):
                hit = True  # 没写重复规则 = 每天
            if hit:
                out.append(e)
        out.sort(key=lambda e: e.get("start", "00:00"))
        return out

    def active_and_next(self, now: dt.datetime):
        """返回 (进行中的日程, 下一场日程, 距下一场分钟数)。"""
        candidates = []
        for day in (now.date() - dt.timedelta(days=1), now.date(), now.date() + dt.timedelta(days=1)):
            for e in self.entries_for(day):
                try:
                    start, end = _interval(e, day)
                except (ValueError, KeyError, AttributeError):
                    continue
                candidates.append((start, end, e))
        active = None
        nxt = None
        nxt_start = None
        for start, end, e in sorted(candidates, key=lambda item: item[0]):
            if start <= now < end:
                active = e
            elif start > now and nxt is None:
                nxt = e
                nxt_start = start
        delta = None
        if nxt and nxt_start:
            delta = max(0, int((nxt_start - now).total_seconds() // 60))
        return active, nxt, delta

    def summary_for(self, now: dt.datetime) -> str:
        """给 LLM 系统提示词用的一句话摘要（有工作计划时优先展示计划）。"""
        active, nxt, delta = self.active_and_next(now)
        parts = []
        if active:
            parts.append(f"{active['start']}-{active['end']} {self._label(active)}（进行中）")
        if nxt:
            parts.append(f"{nxt['start']} {self._label(nxt)}（约 {delta} 分钟后开始）")
        for e in self.entries_for(now.date()):
            if e is not active and e is not nxt:
                parts.append(f"{e['start']}-{e['end']} {self._label(e)}")
        return "；".join(parts) if parts else "今天没有安排"

    @staticmethod
    def _label(e: dict) -> str:
        plan = (e.get("plan") or "").strip()
        return f"{e['title']}：{plan}" if plan else e["title"]
