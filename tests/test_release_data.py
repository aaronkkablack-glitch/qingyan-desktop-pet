"""发布第二轮：数据保护、历史裁剪、命名空间延迟导入。全部本地运行。"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from pet import config as cm, schedule_store as sm, usage_reader as um, chat_panel as cp, game_plugins as gp
from pet.glm_client import GlmClient
app = QApplication.instance() or QApplication([])

def test_failed_backup_prevents_overwrite():
    with tempfile.TemporaryDirectory() as tmp:
        for module, field, action in (
            (cm, "CONFIG_PATH", lambda: cm.Config().save()),
            (sm, "SCHEDULE_PATH", lambda: sm.ScheduleStore().save()),
            (um, "PET_USAGE_PATH", lambda: um.record_pet_usage("m", {"prompt_tokens":1}))):
            path = str(Path(tmp)/field)
            Path(path).write_text("broken")
            with patch.object(module, field, path), patch.object(module, "backup_corrupt", return_value=None):
                try: action()
                except OSError: pass
                assert Path(path).read_text() == "broken"

def test_schedule_mutation_disk_failure_preserves_memory():
    store = sm.ScheduleStore.__new__(sm.ScheduleStore)
    store.entries = [{"id":"old"}]
    with patch.object(store, "save", side_effect=OSError("disk")):
        for action in (lambda: store.add("new"), lambda: store.remove("old")):
            try: action()
            except OSError: pass
            assert store.entries == [{"id":"old"}]

def test_history_backup_and_boundaries():
    cfg = dict(api_key="test", api_base="http://127.0.0.1:1", chat_models=["m"], chat_model="m")
    with tempfile.TemporaryDirectory() as tmp, patch.object(cp, "HISTORY_PATH", str(Path(tmp)/"history.json")):
        Path(cp.HISTORY_PATH).write_text("broken")
        with patch.object(cp, "backup_corrupt", return_value=None):
            panel = cp.ChatPanel(cfg, GlmClient(cfg), None)
            panel.history = [{"role":"user", "content":"x"}]
            panel._persist_history()
            assert Path(cp.HISTORY_PATH).read_text() == "broken"
        panel._history_no_save = False
        panel.history = []
        for i in range(250):
            panel.history.extend([{"role":"user", "content":str(i)},
                                  {"role":"assistant", "content":"ok"}])
        panel._trim_history()
        assert len(panel.history) <= cp.HISTORY_KEEP and panel.history[0]["role"] == "user"
        panel.shutdown()
        panel.close()

def test_delayed_imports_keep_plugin_versions_isolated():
    with tempfile.TemporaryDirectory() as tmp:
        modules = []
        paths_before = list(sys.path)
        for label in ("a", "b"):
            directory = Path(tmp)/label
            directory.mkdir()
            (directory/"engine.py").write_text(f"VALUE='{label}'\n")
            (directory/"plugin.py").write_text(
                "TITLE='test'\ndef create(cfg): return None\ndef later():\n import engine\n return engine.VALUE\n")
            modules.append(gp._load(str(directory/"plugin.py"), label))
        assert [m.later() for m in modules] == ["a", "b"]
        assert "engine" not in sys.modules and sys.path == paths_before
        assert not any(k.startswith("_qingyan_plugin_") for k in sys.modules)

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("Release data boundary tests passed")
