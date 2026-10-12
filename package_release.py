"""白名单生成发布 zip；在临时目录执行实际 exe 两次离线自检。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parent
FILES = [("dist/清言V1.0.exe", "清言V1.0.exe"),
         ("rules_bridge/pikafish-source.zip", "rules-source/pikafish-source.zip"),
         ("rules_bridge/judge.cpp", "rules-source/judge.cpp"),
         ("rules_bridge/build.py", "rules-source/build.py"),
         ("rules_bridge/position_rules.cpp", "rules-source/position_rules.cpp"),
         ("rules_bridge/README.md", "rules-source/README.md"),
         ("README.md", "README.md"), ("游戏规则.md", "游戏规则.md"),
         ("发布与验收.md", "发布与验收.md"),
         ("互动插件/把游戏插件放在这里.txt", "互动插件/把游戏插件放在这里.txt")]


def main():
    artifacts = ROOT / "release"
    artifacts.mkdir(exist_ok=True)
    output = artifacts / "清言V1.0-release.zip"
    with tempfile.TemporaryDirectory(prefix="qingyan-release-") as tmp:
        stage = Path(tmp)
        for source, target in FILES:
            dest = stage / target
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT/source, dest)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QINGYAN_RELEASE_CHECK_ISOLATED="1")
        results = []
        for i in range(2):
            report = stage/f"check-{i}.json"
            subprocess.run([str(stage/"清言V1.0.exe"), "--release-check", str(report)],
                           cwd=stage, env=env, timeout=60, check=True)
            result = json.loads(report.read_text(encoding="utf-8"))
            assert result["ok"] and result["frozen"]
            results.append(result)
        # 自检产生的数据只存在临时目录；zip 只包含指定白名单。
        manifest = {target: hashlib.sha256((stage/target).read_bytes()).hexdigest() for _, target in FILES}
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for _, target in FILES:
                archive.write(stage/target, target)
            archive.writestr("SHA256.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(output) as archive:
            assert set(archive.namelist()) == set(manifest) | {"SHA256.json"}
        (artifacts/"离线发布验证.json").write_text(json.dumps({"checks": results,
            "archive": output.name, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "files": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Release package verified: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
