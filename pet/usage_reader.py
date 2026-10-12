"""Token 用量统计，两个来源：

1. zcode 账号用量：直接读 zcode 本地 sqlite（只读模式，不影响 zcode 运行）
   - 库：~/.zcode/cli/db/db.sqlite（WAL 模式，必须用 file:...?mode=ro URI 打开）
   - 表 model_usage：started_at 为毫秒时间戳(int)，model_id / input_tokens /
     output_tokens / cache_read_input_tokens / computed_total_tokens
2. 桌宠自己的调用量：data/pet_usage.json，按日期+模型累计
"""
import datetime as dt
import json
import os
import sqlite3

from .config import PET_USAGE_PATH, backup_corrupt


def _ms(d: dt.date) -> int:
    return int(dt.datetime.combine(d, dt.time()).timestamp() * 1000)


CACHE_SEC = 30   # 右键菜单每次打开都要用量：短时间内复用结果，不在 UI 线程反复跑全表聚合
_cache: dict = {}


def zcode_usage(db_path: str, max_age: float = CACHE_SEC) -> dict:
    """返回 {today, week, total, models_7d, error}，各条目含 calls/in/out/total。
    max_age 秒内复用上次结果（用量面板「刷新」传 0 强制重查）。"""
    import copy
    import time
    hit = _cache.get(db_path)
    if hit and max_age > 0 and time.monotonic() - hit[0] < max_age and hit[1].get("day") == dt.date.today():
        return copy.deepcopy(hit[1]["out"])
    out = _query(db_path)
    if not out["error"]:
        _cache[db_path] = (time.monotonic(), {"day": dt.date.today(), "out": copy.deepcopy(out)})
    return out


def _query(db_path: str) -> dict:
    out = {"today": None, "week": None, "total": None, "models_7d": [], "error": ""}
    if not os.path.exists(db_path):
        out["error"] = f"找不到数据库: {db_path}"
        return out
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    days7 = today - dt.timedelta(days=6)
    from contextlib import closing
    try:
        # timeout=0.5：遇到 zcode 写锁/checkpoint 时最多卡半秒，而不是默认 5 秒冻住界面；
        # closing 保证异常时连接也会关闭
        uri = f"file:{db_path.as_posix() if hasattr(db_path, 'as_posix') else db_path}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.5)) as con:
            con.row_factory = sqlite3.Row

            def agg(since_ms):
                r = con.execute(
                    "SELECT COUNT(*) c, SUM(input_tokens) i, SUM(output_tokens) o, "
                    "SUM(computed_total_tokens) t, SUM(cache_read_input_tokens) cr "
                    "FROM model_usage WHERE started_at >= ?",
                    (since_ms,)).fetchone()
                return {"calls": r["c"] or 0, "in": r["i"] or 0, "out": r["o"] or 0,
                        "total": r["t"] or 0, "cache_read": r["cr"] or 0}

            out["today"] = agg(_ms(today))
            out["week"] = agg(_ms(monday))
            out["total"] = agg(0)
            rows = con.execute(
                "SELECT model_id m, COUNT(*) c, SUM(input_tokens) i, SUM(output_tokens) o "
                "FROM model_usage WHERE started_at >= ? GROUP BY model_id "
                "ORDER BY SUM(computed_total_tokens) DESC LIMIT 8", (_ms(days7),)).fetchall()
            out["models_7d"] = [(r["m"], r["c"], r["i"] or 0, r["o"] or 0) for r in rows]
    except sqlite3.Error as e:
        out["error"] = f"数据库读取失败: {e}"
    return out


def record_pet_usage(model: str, usage: dict):
    if not usage:
        return
    day = dt.date.today().isoformat()
    data = {"by_date": {}}
    if os.path.exists(PET_USAGE_PATH):
        try:
            with open(PET_USAGE_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("顶层不是对象")
            dates = data.get("by_date", {})
            if not isinstance(dates, dict):
                raise ValueError("by_date不是对象")
            for models in dates.values():
                if not isinstance(models, dict):
                    raise ValueError("模型统计不是对象")
                for counters in models.values():
                    if not isinstance(counters, dict) or any(
                        type(counters.get(key, 0)) is not int or counters.get(key, 0) < 0
                        for key in ("calls", "in", "out")):
                        raise ValueError("用量计数无效")
        except OSError as e:
            # 被占用读不了：这一笔不记，也绝不用空数据覆盖历史
            print(f"[usage] 用量文件读取失败，本次不记账: {e}")
            return
        except ValueError as e:
            bak = backup_corrupt(PET_USAGE_PATH)
            if bak is None:
                return
            print(f"[usage] 用量文件损坏，已备份到 {bak}: {e}")
            data = {"by_date": {}}
    slot = data.setdefault("by_date", {}).setdefault(day, {}).setdefault(
        model, {"calls": 0, "in": 0, "out": 0})
    slot["calls"] += 1
    slot["in"] += usage.get("prompt_tokens", 0)
    slot["out"] += usage.get("completion_tokens", 0)
    os.makedirs(os.path.dirname(PET_USAGE_PATH), exist_ok=True)
    tmp = PET_USAGE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PET_USAGE_PATH)


def pet_usage_summary() -> dict:
    """{today: {...}, total: {...}}，无数据时字段为 0。"""
    today = dt.date.today().isoformat()
    result = {"today": {"calls": 0, "in": 0, "out": 0},
              "total": {"calls": 0, "in": 0, "out": 0}}
    try:
        if os.path.exists(PET_USAGE_PATH):
            with open(PET_USAGE_PATH, encoding="utf-8") as f:
                data = json.load(f).get("by_date", {})
            for day, models in data.items():
                for m, u in models.items():
                    for key in ("calls", "in", "out"):
                        result["total"][key] += u.get(key, 0)
                        if day == today:
                            result["today"][key] += u.get(key, 0)
    except Exception as e:
        print(f"[usage] 桌宠用量读取失败: {e}")
    return result
