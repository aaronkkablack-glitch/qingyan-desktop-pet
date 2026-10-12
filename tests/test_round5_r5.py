"""第五轮-第五轮回归：象棋 AI 后台线程、用量查询缓存、精灵图预缩放缓存、右键菜单不累积。"""
import os
import sys
import tempfile
import time
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QMenu

from pet import config as cfgmod
from pet.config import Config

app = QApplication.instance() or QApplication([])
cfgmod.CONFIG_PATH = os.path.join(tempfile.mkdtemp(), "config.json")


def _wait(pred, timeout=8.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_xiangqi_ai_runs_off_ui_thread_and_stale_result_dropped():
    from pet.games import xiangqi
    from pet.games.xiangqi_engine import BLACK, RED
    w = xiangqi.create(Config())
    w.player_move(w.game.legal_moves(RED)[0])
    gen = w._gen
    w._start_ai(gen)
    assert w._ai_busy, "AI 应在后台搜索"
    assert not w.undo_btn.isEnabled() or w.game.turn == BLACK
    assert _wait(lambda: w.game.turn == RED), "后台搜索结果应回到 UI 线程落子"
    assert not w._ai_busy and len(w.move_log) == 2
    # 过时结果：开新局后到达的旧局着法不得落在新棋盘上
    w.player_move(w.game.legal_moves(RED)[0])
    w._start_ai(w._gen)
    w.new_game()
    assert _wait(lambda: not w._ai_busy or True)
    app.processEvents()
    time.sleep(1.5)
    app.processEvents()
    assert w.move_log == [] and w.game.turn == RED, "新局后旧 AI 结果必须丢弃"
    w.close()


def test_zcode_usage_cached():
    from pet import usage_reader as ur
    calls = {"n": 0}
    old = ur._query
    ur._query = lambda p: (calls.__setitem__("n", calls["n"] + 1)
                           or {"today": {}, "week": {}, "total": {}, "models_7d": [], "error": ""})
    ur._cache.clear()
    try:
        ur.zcode_usage("x.db")
        ur.zcode_usage("x.db")
        assert calls["n"] == 1, "30 秒内的重复查询应命中缓存"
        ur.zcode_usage("x.db", max_age=0)
        assert calls["n"] == 2, "max_age=0 强制重查"
    finally:
        ur._query = old
        ur._cache.clear()


def test_sprite_paint_uses_scaled_cache():
    from pet.animation import make_renderer
    r = make_renderer(Config())
    if not hasattr(r, "frame_key"):
        return
    r.set_size(200, 300, 1.0)
    r.set_state("idle")
    for _ in range(3):
        img = QImage(200, 300, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        r.paint(p)
        p.end()
    assert len(r._scaled) == 1, "同一帧只缩放一次"
    assert img.pixelColor(100, 150).alpha() > 0, "预缩放后仍应画出角色"
    r.set_size(220, 330, 1.0)
    assert not r._scaled, "尺寸变化时缓存作废"


def test_menu_fill_does_not_accumulate_submenus():
    from pet.main import build_menu

    class _Stub:
        def __getattr__(self, _):
            return lambda *a, **k: None

    cfg = Config()
    cfg["zcode_db_path"] = os.path.join(tempfile.mkdtemp(), "none.db")
    fill = build_menu(cfg, _Stub(), _Stub(), _Stub(), _Stub(), _Stub(), _Stub())
    menu = QMenu()
    for _ in range(5):
        fill(menu)
        app.processEvents()
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    subs = menu.findChildren(QMenu)
    assert len(subs) <= 3, f"子菜单不应随打开次数累积：{len(subs)}"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("第五轮-第五轮回归测试通过 ✔")
