"""第四轮安全边界测试：凭据保护和配置范围收敛。"""
import json
import os
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_config_validation_clamps_ranges():
    from pet import config as mod
    old = mod.CONFIG_PATH
    path = os.path.join(tempfile.mkdtemp(), "config.json")
    mod.CONFIG_PATH = path
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"max_tokens": 999999, "pet_height": 1,
                       "water": {"interval_min": 999, "active_start": -5, "active_end": 99},
                       "freelane": {"port": 99999}}, f)
        cfg = mod.Config()
        assert cfg["max_tokens"] == 32768
        assert cfg["pet_height"] == 120
        assert cfg["water"]["interval_min"] == 240
        assert cfg["water"]["active_start"] == 0 and cfg["water"]["active_end"] == 24
        assert cfg["freelane"]["port"] == 65535
    finally:
        mod.CONFIG_PATH = old


def test_plain_api_key_round_trips_without_plaintext_on_windows():
    from pet import config as mod
    old = mod.CONFIG_PATH
    path = os.path.join(tempfile.mkdtemp(), "config.json")
    mod.CONFIG_PATH = path
    try:
        cfg = mod.Config()
        cfg["api_key"] = "unit-test-secret-key"
        cfg.save()
        raw = json.load(open(path, encoding="utf-8"))
        cfg2 = mod.Config()
        if os.name == "nt":
            assert "unit-test-secret-key" not in json.dumps(raw)
            assert cfg2["api_key"] == "unit-test-secret-key"
    finally:
        mod.CONFIG_PATH = old


if __name__ == "__main__":
    test_config_validation_clamps_ranges()
    test_plain_api_key_round_trips_without_plaintext_on_windows()
    print("凭据与配置安全测试通过 ✔")
