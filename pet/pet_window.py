"""桌宠主窗口：透明无边框置顶、可拖拽、右键菜单、点击小跳、气泡说话。

扩展约定（新动作/新立绘）：
- 换形象/渲染方式 → animation.AvatarRenderer 的实现，本窗口不感知细节
- 菜单项由 main 注入（self.menu_builder(menu)），窗口只管触发
"""
import os
import random

from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, QSequentialAnimationGroup,
                            QAbstractAnimation, QRect, QTimer)
from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QAction, QPainter
from PySide6.QtWidgets import QMenu, QWidget

from .animation import AVATARS, make_renderer
from .animation import StaticRenderer
from PySide6.QtGui import QPixmap
from .bubble import BubbleWidget

POKE_LINES = ["戳我干嘛～", "在呢在呢！", "怎么啦？主人~", "嘿嘿，好痒", "清言在听哦~请尽情吩咐清言"]
TICKLE_LINE = "嘿嘿，好痒"  # 这句触发乱跑彩蛋


class PetWindow(QWidget):
    request_chat = Signal()
    request_usage = Signal()
    request_schedule = Signal()
    avatar_switched = Signal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent,
                         Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.cfg = config
        self._drag_offset = QPoint()
        self._press_global = QPoint()
        self._dragged = False
        self.menu_builder = lambda menu: None
        self._state_requests: dict[str, str] = {}
        self._state_priority = {"chat": 60, "zcode": 70, "game": 80,
                                "oneshot": 20, "auto": 50}
        self._flash = None               # 正在播放的瞬时动作（done/error），播完回仲裁
        self._sprite_renderer = None     # 立绘期间暂存的精灵图渲染器（退出立绘复用）
        self._skip_next_release = False  # 双击后的第二次松开不再算单击
        # 聆听动作回待机：复用一个单次计时器（连点 restart，不再每次 new 一个泄漏）
        self._action_revert_timer = QTimer(self)
        self._action_revert_timer.setSingleShot(True)
        self._action_revert_timer.timeout.connect(self._rearbitrate)

        self.bubble = BubbleWidget()
        self._renderer = make_renderer(self.cfg)
        self._content_ratios = {}          # 素材内容占比缓存（'sprite' / 'portrait:<file>'）
        self._anchor_cache = {}
        self._portrait_key = None
        self._ratio("sprite", self._renderer.pixmap())   # 动画素材基准（idle 帧）
        if hasattr(self._renderer, "set_oneshot_callback"):
            self._renderer.set_oneshot_callback(self._finish_oneshot_source)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)
        self._anim_timer.timeout.connect(self._on_tick)
        self._apply_avatar_size()
        self._restore_pos()

        # 闲置睡觉：无互动 idle_sleep_min 分钟后进入 sleeping
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setSingleShot(True)
        self._sleep_timer.timeout.connect(self._enter_sleep)
        self.refresh_sleep_config()

        # 长按出气泡：按住 0.7s → 云朵报时（拖动/快重点击不触发；press/release 事件可靠，
        # 不受鼠标捕获/悬停状态错位影响——此前 enterEvent 与光标轮询两版均不稳定）
        self._status_provider = None
        self._long_pressed = False   # 长按已触发：松开时不得再走单击台词分支
        self._swallow_poke = False   # 确认式气泡的首次点击只关气泡，不触发戳一戳反应
        self._press_timer = QTimer(self)
        self._press_timer.setSingleShot(True)
        self._press_timer.setInterval(700)
        self._press_timer.timeout.connect(self._on_hover_report)

    def set_status_provider(self, fn):
        """fn() -> str|None：当前时段文案（由 main 注入，读日程 store）。"""
        self._status_provider = fn

    def _on_hover_report(self):
        self._long_pressed = True  # 无论有无文案，长按触发后松开都不算单击
        if self._status_provider is None:
            return
        text = self._status_provider()
        if text:
            g = self.geometry()
            try:
                ax, ay = self._content_anchor()
            except Exception:
                ax, ay = g.center().x(), g.top() + 8
            self.bubble.cloud_say(text, (ax, ay), 6000)
            self._bubble_sync_pos = self.pos()   # 云朵同样跟随拖动

    # ---------- 精灵图状态 ----------

    _portrait_mode = False

    # 状态模型（单一事实来源）：
    # - _state_requests：各来源的「持续态」（thinking / recording …），始终维护，立绘模式也不例外；
    # - done/error 是「瞬时事件」：不进持久表。只有发出时该来源是最高优先级（没被更高来源压着）
    #   才播一次，播完由 one-shot 回调调用 _rearbitrate()；被压住的直接丢弃，不会事后补播过时动作。
    # - 任何"回到默认"的入口（拖拽松开 / 唤醒 / one-shot 播完 / 来源清除）都走 _rearbitrate()。

    def set_sprite_state(self, state: str):
        """用户主动切状态（菜单"🎭 动作"= 退出立绘的唯一出口）；
        若当前在立绘模式，先重建精灵图渲染器回到动画。"""
        if not hasattr(self._renderer, "set_state"):
            self._exit_portrait()
        # 任意动作触发（菜单选动作 / zcode 联动 / 聊天状态 / 游戏联动）都顺延睡觉倒计时
        self._reset_sleep_timer()
        self._flash = None     # 用户/仲裁显式切状态，覆盖正在播的瞬时动作
        self._action_revert_timer.stop()   # 别的动作接管后，旧的聆听回待机不能再生效
        self._renderer.set_state(state)

    def _exit_portrait(self):
        renderer = getattr(self, "_sprite_renderer", None) or make_renderer(self.cfg)
        self._sprite_renderer = None
        self._renderer = renderer
        if hasattr(self._renderer, "set_oneshot_callback"):
            self._renderer.set_oneshot_callback(self._finish_oneshot_source)
        self._portrait_mode = False     # 先退出立绘标记，再按动画基准重设尺寸
        self._apply_avatar_size()

    def _winning_source(self):
        if not self._state_requests:
            return None
        return max(self._state_requests, key=lambda s: self._state_priority.get(s, 50))

    def _arbitrated_state(self) -> str:
        src = self._winning_source()
        return self._state_requests[src] if src else "idle"

    def request_sprite_state(self, state: str, source: str = "auto"):
        """自动联动源请求状态；不同来源独立登记，按优先级仲裁。立绘模式只记账不切画面。"""
        if state in ("done", "error"):
            self._state_requests.pop(source, None)   # 这一来源的持续态到此结束
            top = self._winning_source()
            outranked = top is not None and (self._state_priority.get(top, 50)
                                             > self._state_priority.get(source, 50))
            if outranked or getattr(self, "_portrait_mode", False):
                self._rearbitrate()                  # 被压住：丢弃瞬时动作
                return
            self.set_sprite_state(state)
            self._flash = state                      # one-shot 播完再回仲裁结果
            return
        if state == "idle":
            self._state_requests.pop(source, None)
        else:
            self._state_requests[source] = state
        self._rearbitrate()

    def _rearbitrate(self):
        """按请求表重新决定画面；瞬时动作播放中不打断（播完回调会再进来）。"""
        if getattr(self, "_portrait_mode", False) or not hasattr(self._renderer, "set_state"):
            return
        target = self._arbitrated_state()
        if getattr(self, "_flash", None) and target == "idle":
            return  # 庆祝/出错还没播完，等回调
        if self._renderer.current_state() != target:
            self.set_sprite_state(target)

    def _finish_oneshot_source(self):
        """one-shot（done/error）播完：回到仲裁结果。QTimer 延后，避免在 paint 调用栈里切状态。"""
        def _done():
            self._flash = None
            self._rearbitrate()
        QTimer.singleShot(0, _done)

    def set_portrait(self, png_name: str):
        """立绘模式：显示 静态图/ 里的角色整图（少女.png / 成女.png），不播动画；
        拖拽不触发拖拽动画，直到从菜单选动作退出立绘模式。"""
        import os
        path = os.path.join(self.cfg.get("sprite_assets_dir") or "", png_name)
        if not os.path.exists(path):
            self.say(f"找不到立绘文件：{png_name}", 4000)
            return
        self._portrait_mode = True
        self._portrait_key = f"portrait:{png_name}"
        if hasattr(self._renderer, "set_state"):
            # 保留精灵图渲染器：退出立绘时直接复用，不必在 UI 线程重新解码上百帧 PNG
            self._sprite_renderer = self._renderer
        self._flash = None
        self._renderer = StaticRenderer(QPixmap(path))
        self._ratio(self._portrait_key, self._renderer.pixmap())   # 该立绘的内容占比
        self._apply_avatar_size()
        self.update()

    def _reset_sleep_timer(self):
        """活动发生：睡觉倒计时重新开始（任意动作/交互/聊天均视为活动）。
        不再要求计时器已在跑：初始为静态渲染、之后切到动画时也能开始计时。"""
        if self._sleep_enabled:
            self._sleep_timer.start()

    def refresh_sleep_config(self):
        """运行时改了 idle_sleep_min（设置页/聊天工具）后调用，立即按新间隔计时。"""
        try:
            minutes = float(self.cfg.get("idle_sleep_min", 5) or 0)
        except (TypeError, ValueError):
            minutes = 0
        self._sleep_enabled = minutes > 0
        if self._sleep_enabled:
            self._sleep_timer.setInterval(int(minutes * 60_000))
            self._sleep_timer.start()
        else:
            self._sleep_timer.stop()

    def activity(self):
        """外部活动源（聊天打字/收发消息等）调用：顺延睡觉倒计时，睡梦中唤醒。"""
        self._touch_interaction()

    def _touch_interaction(self):
        """任何交互时调用：重置睡觉计时，睡梦中则唤醒（回到仲裁结果，而不是硬切 idle）。"""
        self._reset_sleep_timer()
        if hasattr(self._renderer, "set_state") and self._renderer.current_state() == "sleeping":
            self._rearbitrate()

    def _enter_sleep(self):
        if getattr(self, "_portrait_mode", False):
            return  # 立绘模式不自动进睡觉动画
        if any(state in ("thinking", "recording") for state in self._state_requests.values()):
            self._reset_sleep_timer()
            return  # 聊天/zcode/游戏仍在工作，不进入睡觉
        if hasattr(self._renderer, "set_state"):
            self.set_sprite_state("sleeping")

    # ---------- 形象与渲染 ----------

    def set_height(self, h: int):
        """运行时改桌宠高度（设置窗滑块用）：底部中心锚定不飘移，立即生效。
        语义为"动画模式窗口高度"，立绘模式按内容占比自动换算保持视觉一致。"""
        h = max(120, min(1200, int(h)))
        self.cfg["pet_height"] = h
        self._apply_avatar_size()
        self.update()

    @staticmethod
    def _content_ratio(pm) -> float:
        """素材内容（非透明）高度占整图比例——切换模式时按内容等高换算窗口尺寸，
        避免帧序列（内容~74%）与整图立绘（~99%）切换时角色视觉突变。"""
        from PySide6.QtGui import QImage
        img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
        w, h = img.width(), img.height()
        if not w or not h:
            return 1.0
        ptr = img.constBits()
        data = bytes(ptr)[: img.sizeInBytes()]
        top = bottom = -1
        for y in range(h):
            base = y * w * 4 + 3
            if any(data[base + x * 4] for x in range(0, w, 4)):
                if top < 0:
                    top = y
                bottom = y
        if top < 0:
            return 1.0
        return (bottom - top + 1) / h

    def _ratio(self, key: str, pm) -> float:
        if key not in self._content_ratios:
            self._content_ratios[key] = self._content_ratio(pm)
        return self._content_ratios[key]

    def _display_height(self) -> int:
        """窗口显示高度：动画模式=pet_height；立绘模式按两模式内容占比换算，
        使角色内容视觉高度与动画模式一致。"""
        h = int(self.cfg.get("pet_height", 400))
        if not getattr(self, "_portrait_mode", False):
            return h
        sprite_r = self._content_ratios.get("sprite")
        portrait_r = self._content_ratios.get(self._portrait_key)
        if not sprite_r or not portrait_r:
            return h
        return max(120, min(1200, round(h * sprite_r / portrait_r)))

    def _apply_avatar_size(self, keep_bottom_center=True):
        old_center_bottom = None
        if keep_bottom_center and self.isVisible():
            g = self.geometry()
            old_center_bottom = QPoint(g.center().x(), g.bottom())
        h = self._display_height()          # 立绘模式按内容占比换算，切换无视觉突变
        pm = self._renderer.pixmap()
        w = max(1, round(pm.width() * h / pm.height()))
        self.resize(w, h)
        self._renderer.set_size(w, h, self.devicePixelRatioF())
        if old_center_bottom is not None:
            self.move(old_center_bottom.x() - w // 2, old_center_bottom.y() - h)
        if self._renderer.animated:
            self._anim_timer.start()
        else:
            self._anim_timer.stop()

    def set_avatar(self, key: str):
        if key not in AVATARS:
            return
        self.cfg["avatar"] = key
        self.refresh_renderer()
        self.avatar_switched.emit(key)

    def refresh_renderer(self):
        """按当前 config（avatar/animation）重建渲染器。"""
        self._renderer = make_renderer(self.cfg)
        self._sprite_renderer = None
        self._portrait_mode = False
        self._flash = None
        if hasattr(self._renderer, "set_oneshot_callback"):
            self._renderer.set_oneshot_callback(self._finish_oneshot_source)
        self._apply_avatar_size()
        self._rearbitrate()
        self.update()

    def avatar_name(self) -> str:
        return AVATARS[self.cfg["avatar"]]["name"]

    def _on_tick(self):
        import time
        now = time.monotonic()
        if not hasattr(self, "_last_tick"):
            self._last_tick = now
        self._renderer.tick(min(now - self._last_tick, 0.1))
        self._last_tick = now
        # 精灵图只在帧变化时重绘（idle 实际约 3.5 帧/秒，33ms 无条件重绘大多是浪费）
        key = getattr(self._renderer, "frame_key", None)
        if key is not None:
            k = key()
            if k == getattr(self, "_last_frame_key", None):
                return
            self._last_frame_key = k
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        self._renderer.paint(p)

    def showEvent(self, ev):
        super().showEvent(ev)
        handle = self.windowHandle()
        if handle and not getattr(self, "_screen_hooked", False):
            handle.screenChanged.connect(lambda _screen: self._refresh_screen())
            self._screen_hooked = True
            from PySide6.QtGui import QGuiApplication
            for screen in QGuiApplication.screens():
                screen.logicalDotsPerInchChanged.connect(lambda _dpi: self._refresh_screen())

    def _refresh_screen(self):
        """屏幕/DPI 改变后重建缩放缓存，保留状态和素材实例。"""
        self._anchor_cache.clear()
        self._last_frame_key = None
        self._apply_avatar_size(keep_bottom_center=False)
        scr = self.screen().availableGeometry()
        self.move(max(scr.left(), min(self.x(), scr.right()-self.width()+1)),
                  max(scr.top(), min(self.y(), scr.bottom()-self.height()+1)))
        self._sync_bubble()
        self.update()

    # ---------- 交互 ----------

    def mousePressEvent(self, ev):
        sticky = self.bubble.isVisible() and getattr(self.bubble, "_sticky", False)
        if sticky:
            self.bubble.dismiss()  # 确认提醒：首次点击只关气泡
        # 左键确认消耗本次按压：松开时不再触发戳一戳台词/动作（右键开菜单不受影响）
        self._swallow_poke = sticky and ev.button() == Qt.LeftButton
        # 被确认气泡消耗的左键按压只负责关闭气泡，不唤醒睡觉或重置活动计时。
        if not self._swallow_poke:
            self._touch_interaction()
        if ev.button() == Qt.LeftButton:
            self._long_pressed = False
            self._press_timer.start()
            self._drag_offset = ev.globalPosition().toPoint() - self.pos()
            self._press_global = ev.globalPosition().toPoint()
            self._dragged = False
        elif ev.button() == Qt.RightButton:
            menu = QMenu(self)
            from .theme import menu_qss
            menu.setStyleSheet(menu_qss())
            self.menu_builder(menu)
            menu.exec(ev.globalPosition().toPoint())
            menu.deleteLater()   # 每次右键都 new 一个：用完释放，否则子菜单/动作随右键次数累积

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.LeftButton:
            delta = ev.globalPosition().toPoint() - self._press_global
            if delta.manhattanLength() > 6:
                self._dragged = True
                self._press_timer.stop()
            if self._dragged:
                self.move(ev.globalPosition().toPoint() - self._drag_offset)
                self._sync_bubble()      # 气泡跟着清言一起走（不再被落下/消失）
                if not self._swallow_poke and not getattr(self, "_portrait_mode", False):
                    self.set_sprite_state("dragging")

    def mouseReleaseEvent(self, ev):
        self._press_timer.stop()
        if not self._swallow_poke:
            self._touch_interaction()
        if ev.button() == Qt.LeftButton:
            skip = self._skip_next_release
            self._skip_next_release = False
            if self._dragged:
                if not self._swallow_poke and not getattr(self, "_portrait_mode", False):
                    self._rearbitrate()   # 回到仲裁结果（如 zcode 仍在思考），而不是硬切待机
            elif not self._long_pressed and not self._swallow_poke and not skip:
                # 单击：随机台词；"嘿嘿，好痒"触发乱跑彩蛋；其他台词播聆听动作（立绘模式只台词）
                # 长按已触发云朵的松开不进这里（否则台词气泡会顶掉云朵）
                line = random.choice(POKE_LINES)
                self.say(line, 3000)
                if not getattr(self, "_portrait_mode", False):
                    if line == TICKLE_LINE:
                        self._scurry()
                    else:
                        self._play_listening()
        if self._dragged:
            self._save_pos()

    def _sync_bubble(self):
        """桌宠窗口移动时让气泡跟随（拖动/乱跑彩蛋），保持在屏幕内。"""
        if not self.bubble.isVisible():
            return
        cur = self.pos()
        last = getattr(self, "_bubble_sync_pos", None) or cur
        self._bubble_sync_pos = cur
        delta = cur - last
        if delta.isNull():
            return
        from PySide6.QtGui import QGuiApplication
        s = QGuiApplication.screenAt(self.geometry().center()) or self.screen()
        scr = s.availableGeometry()
        bp = self.bubble.pos() + delta
        bx = max(scr.left() + 4, min(bp.x(), scr.right() - self.bubble.width() - 4))
        by = max(scr.top() + 4, min(bp.y(), scr.bottom() - self.bubble.height() - 4))
        self.bubble.move(bx, by)

    def _play_listening(self):
        """播放聆听动作一轮后回到仲裁结果（无联动时即待机）。"""
        self.set_sprite_state("recording")
        ms = int(self._renderer._durations.get("recording", 4000)) if hasattr(self._renderer, "_durations") else 4000
        self._action_revert_timer.start(ms)

    def _scurry(self):
        """乱跑彩蛋：在附近屏幕区域随机窜 4 段（限屏幕内）。"""
        old = getattr(self, "_scurry_anim", None)
        try:
            if old is not None and old.state() == QAbstractAnimation.Running:
                return   # 上一段乱跑还没结束：不叠加，避免多个动画组同时驱动 pos 抖动
        except RuntimeError:
            pass         # 旧动画组已随 DeleteWhenStopped 释放
        geo = self.screen().availableGeometry()
        group = QSequentialAnimationGroup(self)
        x, y = self.x(), self.y()
        for _ in range(4):
            nx = max(geo.left(), min(x + random.randint(-180, 180), geo.right() - self.width()))
            ny = max(geo.top(), min(y + random.randint(-70, 70), geo.bottom() - self.height()))
            anim = QPropertyAnimation(self, b"pos", self)
            anim.setDuration(230)
            anim.setStartValue(QPoint(x, y))
            anim.setEndValue(QPoint(nx, ny))
            anim.setEasingCurve(QEasingCurve.OutQuad)
            anim.valueChanged.connect(lambda _v: self._sync_bubble())   # 气泡跟着乱跑
            group.addAnimation(anim)
            x, y = nx, ny
        group.finished.connect(self._save_pos)
        group.start(QAbstractAnimation.DeleteWhenStopped)
        self._scurry_anim = group

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            # 事件序列 press→release→dblclick→release：第二次 release 不能再戳一戳
            self._skip_next_release = True
            self.request_chat.emit()

    def _hop(self):
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(160)
        anim.setStartValue(self.pos())
        anim.setEndValue(self.pos() - QPoint(0, 18))
        anim.setEasingCurve(QEasingCurve.OutQuad)
        anim.finished.connect(lambda: self._hop_back())
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._hop_anim = anim  # 防 GC

    def _hop_back(self):
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(220)
        anim.setStartValue(self.pos())
        anim.setEndValue(self._rest_pos())
        anim.setEasingCurve(QEasingCurve.OutBounce)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._hop_anim = anim

    def _rest_pos(self):
        """保证落点不越出屏幕（拖到边缘再小跳时兜底）。"""
        geo = self.screen().availableGeometry()
        r = QRect(self.pos(), self.size())
        if geo.contains(r):
            return self.pos()
        x = max(geo.left(), min(r.left(), geo.right() - r.width()))
        y = max(geo.top(), min(r.top(), geo.bottom() - r.height()))
        return QPoint(x, y)

    # ---------- 位置与气泡 ----------

    def _restore_pos(self):
        from PySide6.QtGui import QGuiApplication
        pos = self.cfg.get("pet_pos")
        if isinstance(pos, list) and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
            # show 之前 self.screen() 恒为主屏：按保存位置的中心点找它所在的屏（副屏不再被夹回主屏）
            scr = QGuiApplication.screenAt(QPoint(x + self.width() // 2, y + self.height() // 2))
            geo = (scr or QGuiApplication.primaryScreen()).availableGeometry()
        else:  # 首次启动放主屏右下角
            geo = QGuiApplication.primaryScreen().availableGeometry()
            x = geo.right() - self.width() - 60
            y = geo.bottom() - self.height() - 40
        self.move(max(geo.left(), min(x, geo.right() - self.width())),
                  max(geo.top(), min(y, geo.bottom() - self.height())))

    def _save_pos(self):
        self.cfg["pet_pos"] = [self.x(), self.y()]
        # 防抖落盘：注销/关机/被强杀时 aboutToQuit 不一定发出，位置不能只存内存
        if not hasattr(self, "_pos_save_timer"):
            self._pos_save_timer = QTimer(self)
            self._pos_save_timer.setSingleShot(True)
            self._pos_save_timer.setInterval(2000)
            self._pos_save_timer.timeout.connect(self._flush_pos)
        self._pos_save_timer.start()

    def _flush_pos(self):
        try:
            self.cfg.save()
        except Exception as e:
            print(f"[pet] 位置保存失败: {e}")

    def _content_anchor(self) -> tuple[int, int]:
        """角色内容的头顶锚点：扫当前帧非透明像素的最顶行，气泡贴近角色而非窗口顶。"""
        from PySide6.QtGui import QImage, QPainter
        g = self.geometry()
        # 帧标识用（状态, 帧序号）而非浮点时间：同一帧复用扫描结果；Sway 等无帧号的按渲染器缓存
        frame = getattr(self._renderer, "frame_key", lambda: id(self._renderer))()
        cache_key = (frame, self.width(), self.height())
        if cache_key in self._anchor_cache:
            return g.center().x(), g.top() + self._anchor_cache[cache_key]
        img = QImage(self.width(), self.height(), QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        self._renderer.paint(p)
        p.end()
        ptr = img.constBits()
        data = bytes(ptr)[: img.sizeInBytes()]
        top = self.height()
        for y in range(self.height()):
            row_base = (y * self.width() + 3) * 4
            if any(data[row_base + x * 4] for x in range(0, self.width(), 4)):
                top = y
                break
        if len(self._anchor_cache) > 256:   # 帧数有限，封顶防长期增长
            self._anchor_cache.clear()
        self._anchor_cache[cache_key] = top
        return g.center().x(), g.top() + top

    def say(self, text: str, ms: int = 7000, sticky: bool = False):
        if (not sticky and self.bubble.isVisible() and getattr(self.bubble, "_sticky", False)):
            return  # 待确认的提醒（喝水/日程）还在：普通台词不顶掉它，用户点一下确认后再说
        g = self.geometry()
        try:
            ax, ay = self._content_anchor()
        except Exception:
            ax, ay = g.center().x(), g.top() + 8
        self.bubble.say(text, (ax, ay), ms, sticky=sticky)
        self._bubble_sync_pos = self.pos()   # 气泡按当前桌宠位置锚定，记录同步基准

    def closeEvent(self, ev):
        self._save_pos()
        self.bubble.close()
        super().closeEvent(ev)
