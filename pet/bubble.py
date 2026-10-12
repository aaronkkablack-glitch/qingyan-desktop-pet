"""对话气泡：独立置顶小窗，带指向桌宠的尾巴，超时自动消失。深色卡风格（theme 同源）。"""
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QWidget

from . import theme


class BubbleWidget(QWidget):
    PADDING = 12
    TAIL = 12
    MAX_W = 280

    def __init__(self):
        super().__init__(None,
                         Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                         Qt.WindowTransparentForInput | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.PlainText)
        self._label.setFont(QFont("Microsoft YaHei UI", 10))
        self._label.setStyleSheet(f"color:{theme.TEXT}; background:transparent;")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._cloud = False
        self._sticky = False

    def dismiss(self):
        """关闭气泡（确认/替换时调用）。"""
        self._timer.stop()
        self.hide()

    def mousePressEvent(self, ev):
        if self._sticky or self._cloud:
            self.dismiss()  # 确认式提醒/长按云朵：点一下即消失
        super().mousePressEvent(ev)

    def say(self, text: str, anchor_top_center, ms: int = 7000, always_above=True, sticky=False):
        """anchor_top_center: 桌宠窗口顶部中心的全局坐标 (x, y)。
        sticky=True: 常驻不自动消失（提醒确认用），点击气泡或桌宠即关闭。"""
        self.dismiss()
        self._sticky = sticky
        # 确认式气泡要接收点击；普通气泡保持鼠标穿透
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not sticky)
        self.setWindowFlag(Qt.WindowTransparentForInput, not sticky)
        self._label.setText(text)
        self._cloud = False
        self._label.setStyleSheet(f"color:{theme.TEXT}; background:transparent;")
        self._label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._place(anchor_top_center, ms, always_above)

    def cloud_say(self, text: str, anchor_top_center, ms: int = 5000):
        """黑色云朵针织气泡（长按报时用），白字，可点按关闭并自动消失。"""
        self._sticky = False  # 复用同一气泡窗，必须清掉上一条的 sticky，否则云朵永不消失
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setWindowFlag(Qt.WindowTransparentForInput, False)
        self._label.setText(text)
        self._cloud = True
        self._label.setStyleSheet("color:#ffffff; background:transparent; font-weight:600;")
        self._label.setAlignment(Qt.AlignCenter)
        self._place(anchor_top_center, ms, True)

    def _place(self, anchor_top_center, ms, always_above):
        fm = QFontMetrics(self._label.font())
        pad = 26 if self._cloud else self.PADDING  # 云朵扇贝边需要更大留白
        w = min(self.MAX_W + (80 if self._cloud else 0),
                max(110, fm.horizontalAdvance(self._label.text()) + pad * 2 + 8))
        self._label.setFixedWidth(w - pad * 2)
        self._label.adjustSize()
        bh = self._label.height() + pad * 2 + self.TAIL
        self.resize(w, bh)
        self._label.move(pad, pad + (0 if not self._cloud else 0))
        ax, ay = anchor_top_center
        x = ax - w // 2
        y = ay - bh - 6 if always_above else ay + 24
        # 按锚点（桌宠头顶）所在的屏夹取，而不是气泡上一次所在的屏（多显示器）
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.screenAt(QPoint(int(ax), int(ay))) or self.screen()
        screen = scr.availableGeometry()
        if y < screen.top() + 4:  # 上方放不下就移到头顶右侧
            x = ax + 40
            y = screen.top() + 40
        x = max(screen.left() + 4, min(x, screen.right() - w - 4))   # 两个分支都要夹右边界
        self.move(x, y)
        self.show()
        self.raise_()
        if not self._sticky:
            self._timer.start(ms)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if getattr(self, "_cloud", False):
            self._paint_cloud(p)
        else:
            path = QPainterPath()
            body_h = self.height() - self.TAIL
            path.addRoundedRect(0.5, 0.5, self.width() - 1, body_h - 1, 12, 12)
            cx = self.width() / 2
            path.moveTo(cx - 7, body_h - 2)
            path.lineTo(cx, self.height() - 1)
            path.lineTo(cx + 7, body_h - 2)
            path.closeSubpath()
            p.setPen(QPen(QColor(theme.BUBBLE_ASSISTANT_BORDER), 1.2))
            p.setBrush(QColor(theme.BUBBLE_ASSISTANT_BG))
            p.drawPath(path)

    def _cloud_path(self, pad: float) -> QPainterPath:
        """云朵轮廓：主体椭圆 + 一圈向内偏移的扇贝圆（融合成蓬松边）。"""
        import math
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)  # 绕数填充：重叠子路径并集而非挖洞
        w, h = self.width(), self.height() - self.TAIL
        cx, cy = w / 2, h / 2
        rx, ry = w / 2 - pad, h / 2 - pad
        path.addEllipse(QRectF(cx - rx, cy - ry, rx * 2, ry * 2))
        n = max(5, int(w / 44))
        for i in range(n):  # 上缘扇贝（圆心内移 14%，鼓包自然融合）
            ang = math.pi * (0.12 + 0.76 * i / (n - 1))
            x = cx - rx * math.cos(ang) * 0.86
            y = cy - ry * math.sin(ang) * 0.86
            r = 13 + pad * 0.6
            path.addEllipse(QRectF(x - r, y - r, r * 2, r * 2))
        for i in range(n):  # 下缘扇贝
            ang = math.pi * (0.12 + 0.76 * i / (n - 1))
            x = cx + rx * math.cos(ang) * 0.86
            y = cy + ry * math.sin(ang) * 0.86
            r = 12 + pad * 0.6
            path.addEllipse(QRectF(x - r, y - r, r * 2, r * 2))
        for sy in (cy - ry * 0.45, cy + ry * 0.45):  # 左右侧扇贝
            for sx in (cx - rx * 0.9, cx + rx * 0.9):
                r = 12 + pad * 0.6
                path.addEllipse(QRectF(sx - r, sy - r, r * 2, r * 2))
        return path

    def _paint_cloud(self, p: QPainter):
        # 描边层：外扩的浅灰云 → 主体黑云覆盖，形成针织包边
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#4a4d58"))
        p.drawPath(self._cloud_path(1.6))
        p.setBrush(QColor("#23252c"))
        p.drawPath(self._cloud_path(0))
        body = self._cloud_path(0)
        # 指向桌宠的小尾巴
        cx = self.width() / 2
        tail = QPainterPath()
        tail.moveTo(cx - 8, self.height() - self.TAIL - 2)
        tail.lineTo(cx, self.height() - 1)
        tail.lineTo(cx + 8, self.height() - self.TAIL - 2)
        tail.closeSubpath()
        p.setBrush(QColor("#23252c"))
        p.drawPath(tail)
        # 针织纹理：V 形针脚网格，裁剪在云内
        p.save()
        p.setClipPath(body)
        stitch = QColor("#565a68")
        stitch.setAlpha(110)
        pen = QPen(stitch, 1.1, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        for row, y in enumerate(range(6, self.height() - self.TAIL, 9)):
            off = 5 if row % 2 else 0
            for x in range(4 + off, self.width() - 2, 10):
                p.drawLine(x, y, x + 3, y + 5)
                p.drawLine(x + 3, y + 5, x + 6, y)
        p.restore()
