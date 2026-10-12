"""发布第一轮：设置事务、凭据失败和地址校验。"""
import copy
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PIL import Image
from pet import config as cm, settings_dialog as sd, credentials
app = QApplication.instance() or QApplication([])

def test_settings_failure_rolls_back_avatar_config_and_memory():
    with tempfile.TemporaryDirectory() as tmp, patch.object(cm, "CONFIG_PATH", str(Path(tmp)/"config.json")), patch.object(sd, "DATA_DIR", tmp):
        cfg = cm.Config()
        before = copy.deepcopy(cfg.d)
        config_bytes = Path(cm.CONFIG_PATH).read_bytes()
        avatar = Path(tmp)/"user_avatar.png"
        Image.new("RGBA", (10,10), "red").save(avatar)
        avatar_bytes = avatar.read_bytes()
        dlg = sd.SettingsDialog(cfg)
        dlg.key_edit.setText("fake-release-key")
        dlg.model_combo.setCurrentText("new-model")
        dlg._pending_avatar = Image.new("RGBA", (160,160), "blue")
        with patch.object(credentials, "encrypt", return_value=None):
            dlg._save()
        assert cfg.d == before
        assert Path(cm.CONFIG_PATH).read_bytes() == config_bytes
        assert avatar.read_bytes() == avatar_bytes
        assert "加密失败" in dlg.result_lab.text()
        dlg.base_edit.setText("file:///secret")
        dlg._save()
        assert "http/https" in dlg.result_lab.text() and cfg.d == before
        dlg.reject()

def test_config_replace_failure_preserves_memory_and_disk():
    with tempfile.TemporaryDirectory() as tmp, patch.object(cm, "CONFIG_PATH", str(Path(tmp)/"config.json")):
        cfg = cm.Config()
        old = copy.deepcopy(cfg.d)
        raw = Path(cm.CONFIG_PATH).read_bytes()
        values = copy.deepcopy(old)
        values["user_name"] = "new"
        with patch.object(cm.os, "replace", side_effect=OSError("disk")):
            try:
                cfg.commit(values)
                raise AssertionError("必须报告失败")
            except OSError:
                pass
        assert cfg.d == old and Path(cm.CONFIG_PATH).read_bytes() == raw

if __name__ == "__main__":
    test_settings_failure_rolls_back_avatar_config_and_memory()
    test_config_replace_failure_preserves_memory_and_disk()
    print("Release settings transaction tests passed")
