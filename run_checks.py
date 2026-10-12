"""统一本地测试入口：python run_checks.py；不启动外部 API 冒烟。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    root = Path(__file__).resolve().parent
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    failed = []
    files = sorted((root / "tests").glob("test_*.py"))
    started = time.monotonic()
    for file in files:
        print(f"[RUN] {file.name}", flush=True)
        try:
            result = subprocess.run([sys.executable, str(file)], cwd=root, env=env, timeout=120)
            if result.returncode:
                failed.append(file.name)
        except subprocess.TimeoutExpired:
            failed.append(file.name + " (timeout)")
    print(json.dumps({"passed": len(files)-len(failed), "failed": failed,
                      "external_api": "not run: space-bunny-free manually accepted by user",
                      "elapsed_seconds": round(time.monotonic()-started, 2)}, ensure_ascii=False))
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
