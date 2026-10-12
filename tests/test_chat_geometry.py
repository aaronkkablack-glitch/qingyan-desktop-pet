"""检查实际 QTextDocument 布局，而非仅检查HTML中有align属性。"""
import os
import sys
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextCursor
from pet import chat_panel as cp
from pet.glm_client import GlmClient
app = QApplication.instance() or QApplication([])

def test_short_user_message_is_close_to_right_avatar():
    cfg = dict(chat_models=['m'], chat_model='m', user_name='用户', api_key='x', api_base='x')
    with patch.object(cp.ChatPanel, '_load_history', lambda self: None):
        panel = cp.ChatPanel(cfg, GlmClient(cfg), None)
    panel.show()
    app.processEvents()
    panel.history = [{'role':'user', 'content':'你好', '_t':'12:00'}]
    panel._render(force=True)
    app.processEvents()
    found = panel.browser.document().find('你好')
    assert not found.isNull()
    found.setPosition(found.selectionStart())
    rect = panel.browser.cursorRect(found)
    width = panel.browser.viewport().width()
    assert rect.x() > width * .65, (rect.x(), width)
    # 两字短消息不能占据半个窗口，字体测量+气泡内边距后靠近右头像。
    assert width - rect.x() < 150, (rect.x(), width)
    panel.close()

def test_short_assistant_message_and_stream_are_compact_on_left():
    cfg = dict(chat_models=['m'], chat_model='m', api_key='x', api_base='x')
    with patch.object(cp.ChatPanel, '_load_history', lambda self: None):
        panel = cp.ChatPanel(cfg, GlmClient(cfg), None)
    panel.show()
    app.processEvents()
    for streaming in (False, True):
        panel.history = [] if streaming else [{'role':'assistant', 'content':'在呢', '_t':'12:00'}]
        panel._stream_buf = '在呢' if streaming else ''
        panel._render(force=True)
        app.processEvents()
        cursor = panel.browser.document().find('在呢')
        assert not cursor.isNull()
        cursor.setPosition(cursor.selectionStart())
        rect = panel.browser.cursorRect(cursor)
        bubble = panel.browser.document().documentLayout().frameBoundingRect(cursor.currentTable())
        assert 40 < rect.x() < 110, rect
        assert bubble.width() < 110, bubble
    panel.close()

if __name__ == '__main__':
    test_short_user_message_is_close_to_right_avatar()
    test_short_assistant_message_and_stream_are_compact_on_left()
    print('Chat actual geometry passed')
