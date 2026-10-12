"""立绘渲染插桩点。

所有形象渲染（现在=静态图；将来=眨眼帧/口型/Live2D/网格变形动效）
都实现 AvatarRenderer 接口，PetWindow 只认接口不认具体实现。

接口约定：
    animated   是否需要持续重绘（True 时 PetWindow 会开定时器调 tick）
    set_size(w, h, dpr)   目标显示尺寸（像素 = 逻辑尺寸 x dpr）
    tick(dt)   推进内部时间（秒）
    paint(painter)       在原点绘制当前帧（窗口大小即画布）
    pixmap()   给托盘图标用的静态缩略图
"""
import os

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtCore import Qt

from .config import ASSETS_DIR

AVATARS = {
    "shao_nv": {"file": "avatar_shaonv.png", "name": "少女", "hair_y_limit": 0.72},
    "cheng_nv": {"file": "avatar_chengnv.png", "name": "成女", "hair_y_limit": 0.58},
}


def avatar_pixmap(key: str) -> QPixmap:
    return QPixmap(os.path.join(ASSETS_DIR, AVATARS[key]["file"]))


class AvatarRenderer:
    animated = False

    def set_size(self, w: int, h: int, dpr: float):
        raise NotImplementedError

    def tick(self, dt: float):
        pass

    def paint(self, p: QPainter):
        raise NotImplementedError

    def pixmap(self) -> QPixmap:
        raise NotImplementedError


class StaticRenderer(AvatarRenderer):
    """静态立绘：整图平滑缩放，零 CPU。

    key 传 AVATARS 的键（assets 立绘），或直接传 QPixmap（如 静态图/ 里的少女/成女整图）。
    """

    def __init__(self, key: str | QPixmap):
        self._src = key if isinstance(key, QPixmap) else avatar_pixmap(key)
        self._w = self._h = 0
        self._dpr = 1.0
        self._scaled: QPixmap | None = None

    def set_size(self, w, h, dpr):
        if (w, h, dpr) != (self._w, self._h, self._dpr):
            self._scaled = None
        self._w, self._h, self._dpr = w, h, dpr

    def paint(self, p: QPainter):
        # 预缩放一次缓存（立绘大图每次重绘都 toImage + 缩放开销很大）
        if self._scaled is None and self._w > 0 and self._h > 0 and not self._src.isNull():
            tw = max(1, int(round(self._w * self._dpr)))
            th = max(1, int(round(self._h * self._dpr)))
            self._scaled = self._src.scaled(tw, th, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self._scaled.setDevicePixelRatio(self._dpr)
        if self._scaled is not None:
            p.drawPixmap(0, 0, self._scaled)

    def pixmap(self) -> QPixmap:
        return self._src


class SwayRenderer(AvatarRenderer):
    """实验版动效：呼吸浮动 + 深色发丝摆动（numpy 网格变形，609x1079 缩到显示尺寸后计算）。

    将来若做成默认，考虑：把发丝掩膜换成手工分层、加速度阻尼、鼠标视差。
    """

    animated = True

    def __init__(self, key: str):
        src = avatar_pixmap(key).toImage().convertToFormat(QImage.Format_RGBA8888)
        w, h = src.width(), src.height()
        self._src = np.frombuffer(src.constBits(), dtype=np.uint8, count=w * h * 4).reshape(
            h, w, 4).copy()
        self._limit = AVATARS[key]["hair_y_limit"]
        self._phase = 0.0
        self._w = self._h = 0
        self._dpr = 1.0
        self._out = QImage()
        self._last_frame_key = None
        self._last_frame = None

    def set_size(self, w, h, dpr):
        self._w, self._h, self._dpr = w, h, dpr
        self._last_frame_key = None
        self._last_frame = None
        pw, ph = int(w * dpr), int(h * dpr)
        from PIL import Image
        pil = Image.fromarray(self._src).resize((pw, ph), Image.LANCZOS)
        self._base = np.asarray(pil).astype(np.float32)
        ys, xs = np.mgrid[0:ph, 0:pw].astype(np.float32)
        self._xs, self._ys = xs, ys
        cy = pw / 2.0
        self._edge_w = np.clip(np.abs(xs - cy) / (pw * 0.5), 0, 1) ** 1.6
        anchor = ph * 0.14
        self._len_w = np.clip((ys - anchor) / (ph - anchor), 0, 1) ** 1.2
        luma = self._base[..., :3] @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
        dark = ((luma < 95) & (self._base[..., 3] > 40)).astype(np.float32) * 255
        from PIL import ImageFilter
        m = Image.fromarray(dark.astype(np.uint8)).filter(ImageFilter.GaussianBlur(7))
        self._hair_w = (np.asarray(m).astype(np.float32) / 255.0) * np.clip(
            (self._limit - ys / ph) / 0.15 + 1, 0, 1)

    def tick(self, dt: float):
        self._phase = (self._phase + dt) % (2 * np.pi * 4)

    def frame_key(self):
        return int(self._phase * 20), self._w, self._h, self._dpr

    def _frame(self) -> np.ndarray:
        t = self._phase
        frame_key = self.frame_key()
        if frame_key == self._last_frame_key and self._last_frame is not None:
            return self._last_frame
        dy = 4.0 * np.sin(t)
        dx = 7.0 * self._len_w * self._edge_w * self._hair_w * np.sin(t * 0.5 + self._ys / 90.0)
        H, W = self._base.shape[:2]
        sx = np.clip(self._xs + dx, 0, W - 1)
        sy = np.clip(self._ys + dy, 0, H - 1)
        x0 = sx.astype(np.int32); y0 = sy.astype(np.int32)
        x1 = np.minimum(x0 + 1, W - 1); y1 = np.minimum(y0 + 1, H - 1)
        fx = (sx - x0)[..., None]; fy = (sy - y0)[..., None]
        a = self._base
        self._last_frame = (a[y0, x0] * (1 - fx) * (1 - fy) + a[y0, x1] * fx * (1 - fy)
                + a[y1, x0] * (1 - fx) * fy + a[y1, x1] * fx * fy).astype(np.uint8)
        self._last_frame_key = frame_key
        return self._last_frame

    def paint(self, p: QPainter):
        img = QImage(self._frame().tobytes(), self._base.shape[1], self._base.shape[0],
                     QImage.Format_RGBA8888).copy()
        img.setDevicePixelRatio(self._dpr)
        p.drawImage(0, 0, img)

    def pixmap(self) -> QPixmap:
        return QPixmap.fromImage(
            QImage(self._src.tobytes(), self._src.shape[1], self._src.shape[0],
                   QImage.Format_RGBA8888).copy())


def make_renderer(config) -> AvatarRenderer:
    key = config["avatar"] if config["avatar"] in AVATARS else "shao_nv"
    assets_dir = config.get("sprite_assets_dir") or ""
    if config.get("animation", "sprite") == "sprite" and assets_dir and os.path.isdir(assets_dir):
        try:
            return SpriteSheetRenderer(assets_dir, durations=config.get("sprite_durations"))
        except Exception as e:
            print(f"[animation] 精灵图素材加载失败，回退静态立绘: {e}")
    if config.get("animation") == "sway":
        return SwayRenderer(key)
    return StaticRenderer(key)


# ---------------------------------------------------------------------------
# 精灵图动画播放器（mori 产物：{state}-sheet.png 1024×1024 4×4、{state}-static-base.png 256×256）
# ---------------------------------------------------------------------------

SPRITE_STATES = ("idle", "sleeping", "recording", "thinking", "done", "error", "walking", "dragging")
ONESHOT_STATES = {"done", "error"}          # 播完一遍自动回 idle
SPRITE_FALLBACK = {"walking": "idle", "dragging": "idle"}  # 无素材时的回退

# 各状态一轮 16 帧的播放时长（ms）——动作节奏由素材语义决定：
# 呼吸/睡觉慢，庆祝/出错是爆发所以快。config.json 的 sprite_durations 可覆盖。
DEFAULT_STATE_DURATION_MS = {
    "idle": 4600, "sleeping": 5000, "recording": 4000, "thinking": 3000,
    "done": 1800, "error": 2000, "walking": 4000, "dragging": 4400,
}


class SpriteSheetRenderer(AvatarRenderer):
    """播放 mori 产出的 4×4 精灵图动画。

    素材解析：{state}-sheet.png 优先（含 "xxx-sheet .png" 空格变体），
    无 sheet 用 {state}-static-base.png 静态显示，再无则按 SPRITE_FALLBACK 回退。
    done/error 为 one-shot：播完一遍触发 oneshot_finished 回调（由外部切回 idle）。
    """

    animated = True

    def __init__(self, assets_dir: str, state: str = "idle", durations: dict | None = None):
        self._dir = assets_dir
        self._sheets: dict[str, QImage] = {}
        self._bases: dict[str, QImage] = {}
        self._frame_seqs: dict[str, list[QImage]] = {}   # 高画质帧序列（720×720 透明帧）
        self._durations = {**DEFAULT_STATE_DURATION_MS, **(durations or {})}
        self._t = 0.0
        self._state = "idle"
        self._oneshot_fired = False
        self._oneshot_cb = None
        self._w = self._h = 0
        self._dpr = 1.0
        self._scaled: dict = {}   # frame_key → 显示尺寸的 QPixmap
        self._sheet_frames = {}
        self._load_all(assets_dir)

    def _load_all(self, assets_dir: str):
        import os
        for name in SPRITE_STATES:
            seq_dir = os.path.join(assets_dir, "帧序列", name)
            if os.path.isdir(seq_dir):
                files = sorted(f for f in os.listdir(seq_dir) if f.lower().endswith(".png"))
                imgs = [QImage(os.path.join(seq_dir, f)) for f in files]
                imgs = [im for im in imgs if not im.isNull()]
                if imgs:
                    self._frame_seqs[name] = imgs
            sheet = self._find(assets_dir, f"{name}-sheet")
            if sheet:
                self._sheets[name] = QImage(sheet)
            base = self._find(assets_dir, f"{name}-static-base")
            if base:
                self._bases[name] = QImage(base)
        if not self._sheets and not self._bases and not self._frame_seqs:
            raise RuntimeError(f"素材目录无有效精灵图: {assets_dir}")

    @staticmethod
    def _find(assets_dir: str, stem: str):
        import os
        for cand in (f"{stem}.png", f"{stem} .png"):
            p = os.path.join(assets_dir, cand)
            if os.path.exists(p):
                return p
        return None

    def set_oneshot_callback(self, cb):
        """one-shot 状态播完时调用 cb()（用于切回 idle）。"""
        self._oneshot_cb = cb

    def set_state(self, state: str):
        if state not in SPRITE_STATES:
            state = "idle"
        # one-shot 即使同名也从头播：否则连续两次庆祝时第二次停在末帧、回调永不触发
        if state != self._state or state in ONESHOT_STATES:
            self._t = 0.0
            self._oneshot_fired = False
        self._state = state

    def current_state(self) -> str:
        return self._state

    def set_size(self, w, h, dpr):
        if (w, h, dpr) != (self._w, self._h, self._dpr):
            self._scaled.clear()   # 尺寸/DPI 变了，预缩放缓存作废
        self._w, self._h, self._dpr = w, h, dpr

    def _scaled_frame(self, img: QImage, key) -> QImage:
        """按显示尺寸 × dpr 预缩放成预乘 ARGB 并缓存：paint 时只做 1:1 贴图，
        不再每帧对 720² 的非预乘 ARGB32 做格式转换 + 平滑缩放。
        用 QImage 而非 QPixmap：无 QGuiApplication（离屏扫描/测试）时建 QPixmap 会直接崩。"""
        pm = self._scaled.get(key)
        if pm is None:
            if len(self._scaled) > 160:   # 帧总数约 112：封顶防止异常 key 无限增长
                self._scaled.clear()
            tw = max(1, int(round(self._w * self._dpr)))
            th = max(1, int(round(self._h * self._dpr)))
            pm = img.convertToFormat(QImage.Format_ARGB32_Premultiplied).scaled(
                tw, th, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(self._dpr)
            self._scaled[key] = pm
        return pm

    def _n_frames(self, state: str) -> int:
        seq = self._frame_seqs.get(state)
        if seq:
            return len(seq)
        return 16 if state in self._sheets else 1

    def tick(self, dt: float):
        """推进时间；one-shot 播完的回调在这里触发（不放在 paint：离屏扫描锚点的 paint
        会误触发，窗口被遮挡/不重绘时又永远不触发）。"""
        self._t += dt
        state = self._state
        if state in ONESHOT_STATES and not self._oneshot_fired:
            n = self._n_frames(state)
            frame_ms = self._durations.get(state, 4600) / max(n, 1)
            if self._t * 1000.0 >= frame_ms * max(n - 1, 1):
                self._oneshot_fired = True
                if self._oneshot_cb:
                    self._oneshot_cb()

    def frame_key(self):
        """当前显示帧的标识（状态, 帧序号）：帧没变就不必重绘/重新扫描锚点。"""
        n = self._n_frames(self._state)
        return self._state, self._frame_index(self._state, n)

    def _frame_index(self, state: str, n_frames: int) -> int:
        """按时长表推进帧序（循环 %n；one-shot 停在末帧）。"""
        frame_ms = self._durations.get(state, 4600) / max(n_frames, 1)
        total = self._t * 1000.0 / frame_ms
        if state in ONESHOT_STATES:
            return min(int(total), n_frames - 1)
        return int(total) % n_frames

    def _resolve(self) -> QImage | None:
        """当前应显示的完整帧 QImage。

        优先级：帧序列（720×720 高画质直供，可变帧数）> 4×4 sheet（裁格）> static-base > 回退链。
        """
        state = self._state
        seq = self._frame_seqs.get(state)
        if seq:
            return seq[self._frame_index(state, len(seq))]
        sheet = self._sheets.get(state)
        if sheet is not None:
            idx = self._frame_index(state, 16)
            side = sheet.width() / 4
            key = (state, idx)
            if key not in self._sheet_frames:
                self._sheet_frames[key] = sheet.copy(int((idx % 4) * side), int((idx // 4) * side),
                                                      int(side), int(side))
            return self._sheet_frames[key]
        base = self._bases.get(state)
        if base is not None:
            return base
        fb = SPRITE_FALLBACK.get(state, "idle")
        seq = self._frame_seqs.get(fb)
        if seq:   # 回退到帧序列时取单帧（此前返回整个 list，paint 时 isNull 会抛错）
            return seq[0]
        return self._sheets.get(fb) or self._bases.get(fb)

    def paint(self, p: QPainter):
        img = self._resolve()
        if img is None or img.isNull():
            return
        if self._w <= 0 or self._h <= 0:
            return
        p.drawImage(0, 0, self._scaled_frame(img, self.frame_key()))

    def pixmap(self) -> QPixmap:
        img = self._resolve()
        return QPixmap.fromImage(img) if img is not None else QPixmap()
