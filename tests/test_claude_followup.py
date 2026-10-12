"""Claude 六至八轮复核问题回归；不访问外网或修改注册表。"""
import os
import sys
import random
import tempfile
from unittest.mock import patch
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PIL import Image
from pet.games.doudizhu_engine import DECK, Move, parse_move, gen_moves, beats
from pet import autostart, game_plugins, settings_dialog as sd
app = QApplication.instance() or QApplication([])


def test_wings_and_ambiguous_plane():
    for wings in ([15, 5], [15, 16], [15, 15, 5, 5]):
        assert parse_move([3]*3 + [4]*3 + wings).type in ("plane1", "plane2")
    assert not parse_move([3]*3 + [4]*3 + [16, 17]).type
    last = parse_move([3]*3 + [4]*3 + [5]*3 + [7, 8, 9])
    cards = [4]*3 + [5]*3 + [6]*3 + [7]*3
    assert beats(parse_move(cards, last), last)
    assert any(m.cards == cards for m in gen_moves(cards, last))


def test_candidates_roundtrip():
    rng = random.Random(20261011)
    for _ in range(120):
        hand = rng.sample(DECK, 20)
        opening = gen_moves(hand, Move.pass_move())
        for last in [Move.pass_move(), parse_move([14]), parse_move([3]*3+[4]*3+[5,6])]:
            for m in gen_moves(hand, last):
                p = parse_move(m.cards, last)
                assert (m.type, m.rank, m.length) == (p.type, p.rank, p.length), (m,p)
                assert beats(p, last)
        assert opening


def test_autostart_empty_stale_and_current():
    class Key:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    with patch.object(autostart.winreg, "OpenKey", return_value=Key()):
        for value, expected in (("", False), ('"C:/old.exe"', False), (autostart._command(), True)):
            with patch.object(autostart.winreg, "QueryValueEx", return_value=(value, 1)):
                assert autostart.is_enabled() is expected


def test_avatar_memory_cancel_reset_and_save():
    class Cfg(dict):
        def save(self): pass
    cfg = Cfg(chat_models=["m"], chat_model="m", api_base="https://example.com", api_key="k")
    with tempfile.TemporaryDirectory() as tmp, patch.object(sd, "DATA_DIR", tmp):
        target = Path(tmp)/"user_avatar.png"
        Image.new("RGBA", (10,10), "red").save(target)
        original = target.read_bytes()
        dlg = sd.SettingsDialog(cfg)
        dlg._pending_avatar = Image.new("RGBA", (160,160), "blue")
        dlg._refresh_avatar_preview()
        dlg.reject()
        assert target.read_bytes() == original
        dlg = sd.SettingsDialog(cfg)
        dlg._pending_avatar = Image.new("RGBA", (160,160), "blue")
        dlg._reset_avatar()
        assert dlg._pending_avatar is None and target.read_bytes() == original
        dlg.reject()
        dlg = sd.SettingsDialog(cfg)
        dlg._pending_avatar = Image.new("RGBA", (160,160), "blue")
        with patch.object(sd.os, "replace", side_effect=OSError("拒绝")):
            dlg._save()
        assert "保存失败" in dlg.result_lab.text() and target.read_bytes() == original
        dlg._save()
        assert target.read_bytes() != original


def test_plugin_packages_and_lazy_create():
    with tempfile.TemporaryDirectory() as tmp, patch.object(game_plugins, "plugin_root", return_value=tmp):
        for label in ("first", "second"):
            directory = Path(tmp)/label
            (directory/"engine").mkdir(parents=True)
            (directory/"engine"/"__init__.py").write_text(f"VALUE='{label}'\n")
            (directory/"plugin.py").write_text("TITLE='test'\ndef create(cfg):\n import engine\n return engine.VALUE\n")
            assert game_plugins._create_plugin_window(str(directory/"plugin.py"), {}) == label
            assert "engine" not in sys.modules


def test_shutdown_callbacks_do_not_write_history():
    from pet.chat_panel import ChatPanel
    class Closed:
        _closing = True
    closed = Closed()
    ChatPanel._on_failed(closed, "取消")
    ChatPanel._on_tool_round_error(closed, "取消")
    ChatPanel._on_tool_round_done(closed, "旧回复", [], {})


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("Claude复核问题回归通过")
