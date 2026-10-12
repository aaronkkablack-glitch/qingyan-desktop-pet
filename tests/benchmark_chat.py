"""400条历史Qt富文本布局基线；临时历史、不调用API。"""
import os
import sys
import time
import statistics
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from pet.chat_panel import ChatPanel
from pet.glm_client import GlmClient
app=QApplication([])
cfg=dict(api_key="x",api_base="http://127.0.0.1:1",chat_model="m",chat_models=["m"])
with patch.object(ChatPanel,"_load_history",lambda self:None):
    panel=ChatPanel(cfg,GlmClient(cfg),None)
panel.show(); app.processEvents()
panel.history=[{"role":"user" if i%2==0 else "assistant","content":"中文聊天内容，用于布局测量。"*8,"_t":"12:00"} for i in range(400)]
samples=[]
for i in range(5):
    start=time.perf_counter(); panel._render(force=True); app.processEvents()
    samples.append((time.perf_counter()-start)*1000)
print("400 messages render median_ms=%.2f max_ms=%.2f"%(statistics.median(samples),max(samples)))
panel.shutdown(); panel.close()
