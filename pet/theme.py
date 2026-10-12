# -*- coding: utf-8 -*-
"""深色主题 token 与 QSS 生成器（与 usage_panel 的设计语言同源）。

所有面板（聊天/日程/用量/菜单/气泡）从这里取色，改主题只动这一个文件。
"""

# ---- 基础色板 ----
BG = "#17181c"          # 窗口底
CARD = "#1f2127"        # 卡片
CARD_ALT = "#1b1d23"    # 次级卡片/行
TRACK = "#2a2c34"       # 进度/分隔
HOVER = "#31343d"       # 交互悬停
TEXT = "#f4f4f5"        # 主文字
TEXT_DIM = "#d8dae2"    # 次文字
TEXT_MUTE = "#8b8d98"   # 弱文字
GREEN = "#34d399"       # 主强调（green 胶囊）
GREEN_DEEP = "#10b981"
BLUE = "#4f7cff"        # 次强调（模型条/我方气泡）
AMBER = "#f59e0b"       # 警示/次数
RED = "#ef4444"         # 错误
BUBBLE_ASSISTANT_BG = "#262932"   # 清言气泡底
BUBBLE_ASSISTANT_BORDER = "#3a3d47"

FONT = "'Microsoft YaHei UI', 'Segoe UI'"


def scrollbar():
    return f"""
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {TRACK}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {HOVER}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """


def tab() -> str:
    """QTabWidget 顶部标签页（设置页等分页对话框用）。"""
    return f"""
    QTabWidget::pane {{ border: 1px solid {TRACK}; border-radius: 8px;
                       background: {CARD_ALT}; }}
    QTabBar::tab {{ background: transparent; color: {TEXT_MUTE}; padding: 6px 20px;
                   border-top-left-radius: 8px; border-top-right-radius: 8px;
                   margin-right: 2px; }}
    QTabBar::tab:hover {{ color: {TEXT_DIM}; }}
    QTabBar::tab:selected {{ background: {CARD_ALT}; color: {TEXT};
                             border: 1px solid {TRACK}; border-bottom: none; }}
    """


def menu_qss() -> str:
    return f"""
    QMenu {{
        background: {CARD}; color: {TEXT_DIM}; border: 1px solid {BUBBLE_ASSISTANT_BORDER};
        border-radius: 10px; padding: 6px; font-family: {FONT};
    }}
    QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 6px; font-size: 13px; }}
    QMenu::item:selected {{ background: {HOVER}; color: {TEXT}; }}
    QMenu::item:disabled {{ color: {TEXT_MUTE}; }}
    QMenu::separator {{ height: 1px; background: {TRACK}; margin: 5px 8px; }}
    QMenu::tearoff {{ height: 0; border: 0; }}
    """


def button(primary=False, danger=False) -> str:
    """完整规则块形式（setStyleSheet 里裸声明+子规则混写会 parse 失败）。"""
    if primary:
        return (f"QPushButton {{ background: {GREEN_DEEP}; color: white; border: none;"
                f"border-radius: 8px; padding: 6px 18px; font-size: 13px; }}"
                f"QPushButton:hover {{ background: {GREEN}; }}"
                f"QPushButton:disabled {{ background: {TRACK}; color: {TEXT_MUTE}; }}")
    if danger:
        return (f"QPushButton {{ background: rgba(239,68,68,0.14); color: {RED}; border: none;"
                f"border-radius: 8px; padding: 6px 18px; font-size: 13px; }}"
                f"QPushButton:hover {{ background: rgba(239,68,68,0.25); }}")
    return (f"QPushButton {{ background: {CARD_ALT}; color: {TEXT_DIM}; border: 1px solid {TRACK};"
            f"border-radius: 8px; padding: 6px 16px; font-size: 13px; }}"
            f"QPushButton:hover {{ background: {HOVER}; color: {TEXT}; }}"
            f"QPushButton:disabled {{ color: {TEXT_MUTE}; }}")


def input_box(multiline=False) -> str:
    base = (f"background: {CARD_ALT}; color: {TEXT}; border: 1px solid {TRACK};"
            f"border-radius: 8px; padding: 6px 10px; font-size: 13px;"
            f"selection-background-color: {BLUE};")
    if multiline:
        base += "font-family: 'Microsoft YaHei UI';"
    return base


def combo() -> str:
    return f"""
    QComboBox {{ background: {CARD_ALT}; color: {TEXT_DIM}; border: 1px solid {TRACK};
                border-radius: 8px; padding: 4px 26px 4px 10px; font-size: 13px; }}
    QComboBox:hover {{ border-color: {BUBBLE_ASSISTANT_BORDER}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent;
                             border-right: 4px solid transparent; border-top: 6px solid {TEXT_MUTE}; margin-right: 8px; }}
    QComboBox QAbstractItemView {{ background: {CARD}; color: {TEXT_DIM}; border: 1px solid {BUBBLE_ASSISTANT_BORDER};
                                  selection-background-color: {HOVER}; selection-color: {TEXT}; outline: none; }}
    """


def table() -> str:
    return f"""
    QTableWidget {{ background: {CARD}; color: {TEXT_DIM}; border: 1px solid {TRACK};
                   border-radius: 10px; gridline-color: {TRACK}; font-size: 12px; }}
    QTableWidget::item {{ padding: 4px 8px; }}
    QTableWidget::item:selected {{ background: rgba(79,124,255,0.18); color: {TEXT}; }}
    QHeaderView::section {{ background: {CARD_ALT}; color: {TEXT_MUTE}; border: none;
                            border-bottom: 1px solid {TRACK}; padding: 6px 8px; font-size: 12px; }}
    QTableCornerButton::section {{ background: {CARD_ALT}; border: none; }}
    """


def label(color=TEXT_DIM, size=13, weight=400) -> str:
    return f"color: {color}; font-size: {size}px; font-weight: {weight}; background: transparent; border: none;"
