# -*- coding: utf-8 -*-
"""probe_models.py —— 逐个探测免费车道上"今天真正能用"的模型。

直连上游 `zen/v1/models` 拿免费名单，然后对每个模型发一条桌宠同形状的最小请求
（带真实工具 + 四件套诱饵，非流式，max_tokens 很小），按返回状态分类：

    ✅ 可用       200 且返回正常补全
    ❌ 不可路由   401 ModelError（在目录里但上游不路由）
    ❌ 资格门     403 FreeTierError（该模型对客户端指纹的校验更严）
    ⚠️ 其它       200 里裹错误 / 5xx / 超时等（看备注）

**注意：必须直连上游探测**（脚本就是这么做的）。若走桌宠代理（127.0.0.1:8787），
代理会自动回退到 fallback 模型，返回值永远是 200，探测结果就失真了。

用法（会消耗少量会话额度，属正常）：
    python probe_models.py                # 用本目录既有的会话
    python probe_models.py --new-session  # 用全新会话探测（不打扰既有额度）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from freelane import (  # noqa: E402  （同目录模块，直连导入）
    UPSTREAM,
    FreelaneProxy,
    _load_session,
    _OPENER,
    classify,
    prepare_payload,
)


class ProbeError(Exception):
    """取免费名单失败（网络 / 上游异常），带给人看的提示。"""

PET_LIKE_TOOLS = [
    {"type": "function", "function": {
        "name": "open_app",
        "description": "打开本地应用程序。",
        "parameters": {"type": "object", "properties": {"app": {"type": "string"}}, "required": ["app"]}}},
    {"type": "function", "function": {
        "name": "list_apps",
        "description": "列出可打开的应用清单",
        "parameters": {"type": "object", "properties": {}}}},
]


def fetch_free_models(proxy: FreelaneProxy) -> list[str]:
    req = urllib.request.Request(f"{UPSTREAM}/zen/v1/models",
                                 headers=proxy.upstream_headers(False))
    try:
        with _OPENER.open(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ProbeError(f"取模型清单失败：上游 HTTP {e.code}") from e
    except (urllib.error.URLError, OSError) as e:      # 断网 / DNS / 超时 / SSL
        raise ProbeError(f"连不上上游 {UPSTREAM}（{type(e).__name__}: {e}），检查网络后再试") from e
    except ValueError as e:
        raise ProbeError(f"上游模型清单不是合法 JSON：{e}") from e
    if not isinstance(data, dict):
        raise ProbeError("上游模型清单格式异常")
    return [m["id"] for m in (data.get("data") or [])
            if isinstance(m, dict) and isinstance(m.get("id"), str)
            and "-free" in m["id"].lower()]


def probe_one(proxy: FreelaneProxy, model: str):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 128,
        "tools": PET_LIKE_TOOLS,
    }
    body, _added = prepare_payload(payload, proxy.aliases)
    t0 = time.monotonic()
    result = proxy.attempt(body, stream=False)
    dt = time.monotonic() - t0
    kind = result[0]
    if kind in ("json", "completion"):
        raw = result[2]
        try:
            d = raw if isinstance(raw, dict) else json.loads(raw.decode("utf-8"))
        except ValueError:
            return "⚠️ 其它", dt, "200 但响应不是 JSON"
        if not isinstance(d, dict):
            return "⚠️ 其它", dt, "200 但响应格式异常"
        # 200 里裹错误体不算可用（attempt 已分类过一次，这里再兜一层）
        ekind, detail = classify(200, json.dumps(d).encode("utf-8"))
        if ekind != "ok" or d.get("error"):
            return "⚠️ 其它", dt, f"200 裹错误 {ekind}: {str(detail)[:60]}"
        if not d.get("choices"):
            return "⚠️ 其它", dt, "200 但没有 choices"
        msg = ((d.get("choices") or [{}])[0].get("message") or {})
        text = (msg.get("content") or "").strip()
        calls = msg.get("tool_calls") or []
        note = f"正文 {len(text)} 字" if text else (f"tool_calls×{len(calls)}" if calls else "空回复")
        return "✅ 可用", dt, note
    if kind == "error":
        status, ekind, detail = result[1], result[2], result[3]
        label = {"model": "❌ 不可路由", "gate": "❌ 资格门", "region": "❌ 地区门",
                 "quota": "❌ 额度打满"}.get(ekind, "⚠️ 其它")
        return label, dt, f"{status} {detail[:70]}"
    return "⚠️ 网络错误", dt, str(result[3])[:70]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="探测免费车道今天可用的模型（直连上游）")
    ap.add_argument("--new-session", action="store_true", help="用全新会话探测")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pet.config import DATA_DIR
    from freelane import mint_session
    proxy = FreelaneProxy(data_dir=DATA_DIR)
    # 临时探测会话只存在内存，不能覆盖桌宠的持久会话。
    proxy.session = mint_session() if args.new_session else _load_session(proxy.state_path)

    try:
        models = fetch_free_models(proxy)
    except ProbeError as e:
        print(f"❌ {e}")
        return 2
    print(f"免费名单 {len(models)} 个｜会话 {proxy.session}")
    print("-" * 72)

    usable = []
    for m in models:
        label, dt, note = probe_one(proxy, m)
        if label == "✅ 可用":
            usable.append(m)
        print(f"{m:<38} {label}  {dt:5.1f}s  {note}")

    print("-" * 72)
    if usable:
        print(f"今天可用 {len(usable)}/{len(models)}：")
        for m in usable:
            print(f"  {m}")
        if proxy.fallback_model not in usable:
            print(f"⚠️ 回退模型 {proxy.fallback_model} 今天不可用！可在 config.json 的 "
                  f"freelane.fallback_model 换一个上面可用的。")
    else:
        print("今天没有可用的免费模型（上游整体收紧或地区受限）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
