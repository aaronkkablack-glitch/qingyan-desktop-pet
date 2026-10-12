"""接手第九轮：结构损坏、记账故障、规则恢复和插件相对子包。"""
import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from pet import schedule_store as ss, usage_reader as ur, game_plugins as gp
from pet.chat_panel import ChatPanel
from pet.games.xiangqi import Xiangqi
app=QApplication.instance() or QApplication([])

def test_malformed_schedule_is_backed_up():
    with tempfile.TemporaryDirectory() as tmp, patch.object(ss,"SCHEDULE_PATH",str(Path(tmp)/"s.json")):
        Path(ss.SCHEDULE_PATH).write_text(json.dumps({"entries":[None]}))
        store=ss.ScheduleStore()
        assert store.entries==[]
        assert list(Path(tmp).glob("*.corrupt-*"))

def test_bad_usage_structure_is_backed_up():
    with tempfile.TemporaryDirectory() as tmp, patch.object(ur,"PET_USAGE_PATH",str(Path(tmp)/"u.json")):
        Path(ur.PET_USAGE_PATH).write_text(json.dumps({"by_date":[]}))
        ur.record_pet_usage("m",{"prompt_tokens":1,"completion_tokens":2})
        assert list(Path(tmp).glob("*.corrupt-*"))

def test_usage_failure_does_not_block_turn_end():
    class Panel:
        _req_model="m"
        cfg={"chat_model":"m"}
    with patch.object(ur,"record_pet_usage",side_effect=OSError("disk")):
        assert "记账失败" in ChatPanel._usage_status(Panel(),{"total_tokens":1})

def test_rules_recovery_clears_warning():
    class Window:
        game=object()
        _rules_warned=True
    window=Window()
    with patch("pet.xiangqi_rules.game_result",return_value="ongoing"):
        assert not Xiangqi._adjudicate(window)
    assert not window._rules_warned

def test_relative_subpackage_import():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        (root/"engine"/"sub").mkdir(parents=True)
        (root/"engine"/"__init__.py").write_text("from . import sub\nVALUE=sub.VALUE\n")
        (root/"engine"/"sub"/"__init__.py").write_text("VALUE=42\n")
        (root/"plugin.py").write_text("import engine\nTITLE=str(engine.VALUE)\n")
        assert gp._load(str(root/"plugin.py"),"test").TITLE=="42"

if __name__=="__main__":
    for name,fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("Handoff regression passed")
