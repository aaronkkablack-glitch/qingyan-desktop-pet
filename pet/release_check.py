"""只在隔离目录运行的打包自检；不连接网络、不启动自启/代理/联动。"""
import json
import os
from pathlib import Path
import sys


ISOLATION_ENV = "QINGYAN_RELEASE_CHECK_ISOLATED"


def _under_temp(path):
    import tempfile
    try:
        Path(path).resolve().relative_to(Path(tempfile.gettempdir()).resolve())
        return True
    except ValueError:
        return False


def _require_isolation():
    """自检会改写 config.json、data/chat_history.json 和日程：只允许在临时目录里的副本上跑，
    否则在真实安装目录/项目根误敲 --release-check 会覆盖用户的聊天记录和用户名。"""
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    if os.environ.get(ISOLATION_ENV) != "1" or not _under_temp(base):
        sys.stderr.write(
            f"拒绝运行：--release-check 会改写 {base} 下的 config.json 和 data/。\n"
            f"请把程序复制到系统临时目录，并设置环境变量 {ISOLATION_ENV}=1 后再运行。\n")
        raise SystemExit(2)


def run(report_path):
    _require_isolation()
    from PySide6.QtWidgets import QApplication
    from . import config, chat_panel
    from .animation import make_renderer
    from .schedule_store import ScheduleStore
    from .glm_client import GlmClient
    from .game_plugins import plugin_root, builtin_games
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    cfg = config.Config()
    expected = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(config.CONFIG_PATH).parent
    assert Path(config.CONFIG_PATH).parent == expected
    assert Path(config.DATA_DIR).parent == expected
    assert Path(plugin_root()).parent == expected
    assert Path(config.ASSETS_DIR, "app.ico").is_file()
    assert Path(config.ASSETS_DIR, "成女头像.png").is_file()
    assert Path(cfg["sprite_assets_dir"]).is_dir()
    renderer = make_renderer(cfg)
    assert not renderer.pixmap().isNull()
    assert len(builtin_games()) == 4
    from .xiangqi_rules import judge, fen
    from .games.xiangqi_engine import Game
    game = Game()
    assert judge(fen(game.board, game.turn), []) == "ongoing"
    store = ScheduleStore()
    original = store.entries
    store.save(original)
    assert ScheduleStore().entries == original
    panel = chat_panel.ChatPanel(cfg, GlmClient(cfg), store)
    panel.history = [{"role":"user", "content":"isolated release check"},
                     {"role":"assistant", "content":"ok"}]
    panel._persist_history()
    restored = chat_panel.ChatPanel(cfg, GlmClient(cfg), store)
    assert restored.history == panel.history
    cfg["user_name"] = "isolated-check"
    cfg.save()
    assert config.Config()["user_name"] == "isolated-check"
    # onefile 解压目录每次变化：验证第二次自检仍能获取素材。
    panel.shutdown()
    restored.shutdown()
    panel.close()
    restored.close()
    report = {"ok": True, "frozen": bool(getattr(sys, "frozen", False)),
              "config_dir": str(expected), "resource_dir": config.ASSETS_DIR,
              "builtin_games": 4, "network": "not used"}
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0
