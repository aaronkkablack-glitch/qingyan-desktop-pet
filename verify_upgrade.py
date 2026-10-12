"""隔离目录执行旧版→新版→旧版，并核对自检产生的持久数据。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("old_exe")
    parser.add_argument("new_exe")
    args = parser.parse_args()
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QINGYAN_RELEASE_CHECK_ISOLATED="1")
    with tempfile.TemporaryDirectory(prefix="qingyan-upgrade-") as tmp:
        root = Path(tmp)
        exe = root / "清言V1.0.exe"
        results = []
        baseline = None
        for index, source in enumerate((args.old_exe, args.new_exe, args.old_exe)):
            shutil.copy2(source, exe)
            report = root / f"check-{index}.json"
            subprocess.run([str(exe), "--release-check", str(report)], env=env, cwd=root,
                           timeout=60, check=True)
            result = json.loads(report.read_text(encoding="utf-8"))
            assert result["ok"]
            # Config 中的打包临时路径不参与语义比较；自检使用相同固定内容。
            config = json.loads((root/"config.json").read_text(encoding="utf-8"))
            config.pop("sprite_assets_dir", None)
            state = {"config": config, "data": {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (root/"data").rglob("*") if p.is_file()}}
            if baseline is None:
                baseline = state
            else:
                assert state == baseline, "升级或回滚改变持久数据"
            results.append({"stage": ("old", "new", "rollback")[index], "ok": True})
        print(json.dumps({"upgrade": results, "scope": "isolated synthetic config/schedule/chat"}))


if __name__ == "__main__":
    main()
