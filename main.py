"""GLM 桌宠启动入口：python main.py（或 pythonw main.py 免黑窗）"""
import sys

from pet.main import main

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--release-check":
        from pet.release_check import run
        sys.exit(run(sys.argv[2]))
    sys.exit(main())
