"""构建规则子程序；固定上游源码，裁去仅用于搜索缓存的预取调用。"""
import argparse
import subprocess
import re
from pathlib import Path
REVISION = "d3adf358ce3dc6d68d9caf2cba338a455a4654d7"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("source")
    p.add_argument("zig")
    args = p.parse_args()
    root = Path(__file__).resolve().parent
    src = Path(args.source)/"src"
    if (Path(args.source)/".git").exists():
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.source, text=True).strip()
        assert revision == REVISION
    text = (src/"position.cpp").read_text(encoding="utf-8")   # 中文 Windows 默认 GBK，不指定会读错
    text = text.replace('UCIEngine::square(pop_lsb(b))', 'std::to_string(int(pop_lsb(b)))')
    text = re.sub(r'    if \(tt\)\n        prefetch\(tt->first_entry\(adjust_key60\(k\)\)\);', '', text)
    generated = root/"position_rules.cpp"
    generated.write_text(text, encoding="utf-8")
    command = [args.zig, "c++", "-std=c++17", "-O2", "-DNDEBUG", "-DIS_64BIT",
               "-Wno-nullability-completeness", "-I", str(src), str(root/"judge.cpp"), str(generated)]
    command += [str(src/f) for f in ("movegen.cpp", "attacks.cpp", "bitboard.cpp", "nnue/features/half_ka_v2_hm.cpp")]
    command += ["-o", str(root/"judge.exe")]
    subprocess.run(command, check=True)

if __name__ == "__main__": main()
