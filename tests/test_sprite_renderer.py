"""SpriteSheetRenderer 单元测试：帧序列播放、one-shot 回调、回退链。
运行: python -m pytest tests/test_sprite_renderer.py -q  或 QT_QPA_PLATFORM=offscreen python tests/test_sprite_renderer.py
"""
import os
import shutil
import sys
for _s in (sys.stdout, sys.stderr):  # Windows GBK 控制台下 ✔ 等字符不应让测试以非零退出
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QColor, QImage, QPainter

from pet.animation import SpriteSheetRenderer

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_sprites")


def make_frames(root: str, state: str, colors) -> None:
    """往 root/帧序列/{state}/ 写 f01..fNN 纯色帧（colors[i]=(r,g,b)），用于断言当前播放帧。"""
    d = os.path.join(root, "帧序列", state)
    os.makedirs(d, exist_ok=True)
    for i, (r, g, b) in enumerate(colors):
        img = QImage(64, 64, QImage.Format_RGBA8888)
        img.fill(QColor(r, g, b, 255))
        img.save(os.path.join(d, f"f{i + 1:02d}.png"))


def center_color(img: QImage) -> tuple:
    c = img.pixelColor(img.width() // 2, img.height() // 2)
    return (c.red(), c.green(), c.blue())


def setup_renderer(tmpdir, seqs: dict):
    os.makedirs(tmpdir, exist_ok=True)
    for name, colors in seqs.items():
        make_frames(tmpdir, name, colors)
    # 统一 1280ms/16帧（80ms/帧），断言数学保持简单
    return SpriteSheetRenderer(tmpdir, durations={n: 1280 for n in seqs})


def test_default_durations_table():
    """不传 durations 时用内置默认表：idle 4600ms/轮，t=2.3s 应在帧 8（16帧的中间）。"""
    colors = [(i * 16, 0, 255 - i * 16) for i in range(16)]
    r = setup_renderer(os.path.join(TMP, "s4"), {"idle": colors})
    from pet.animation import DEFAULT_STATE_DURATION_MS
    r._durations = dict(DEFAULT_STATE_DURATION_MS)   # 落到内置默认表（idle=4600）
    r.set_size(256, 256, 1.0)
    r.set_state("idle"); r._t = 2.3  # 2300/287.5 = 帧 8
    img = QImage(256, 256, QImage.Format_RGBA8888); img.fill(0)
    p = QPainter(img); r.paint(p); p.end()
    assert center_color(img) == colors[8], f"默认4600ms下 t=2.3s 应为帧9, got {center_color(img)}"


def test_frames_dir_playback():
    """帧序列直供：720×720 高清帧按可变帧数播放。"""
    d = os.path.join(TMP, "s5")
    os.makedirs(os.path.join(d, "帧序列", "idle"), exist_ok=True)
    for i in range(4):
        img = QImage(720, 720, QImage.Format_RGBA8888)
        img.fill(QColor(i * 60, 255 - i * 60, 128, 255))
        img.save(os.path.join(d, "帧序列", "idle", f"f{i+1:02d}.png"))
    r = SpriteSheetRenderer(d, durations={"idle": 4000})
    r.set_size(400, 400, 1.0)
    r.set_state("idle"); r._t = 0.0
    img = QImage(400, 400, QImage.Format_ARGB32); img.fill(0)
    p = QPainter(img); r.paint(p); p.end()
    c = img.pixelColor(200, 200)
    assert (c.red(), c.green()) == (0, 255), f"应显示高清帧1, got {(c.red(), c.green())}"
    r._t = 1.0  # 4000ms/4帧=1000ms → 帧2
    img = QImage(400, 400, QImage.Format_ARGB32); img.fill(0)
    p = QPainter(img); r.paint(p); p.end()
    c = img.pixelColor(200, 200)
    assert (c.red(), c.green()) == (60, 195), f"t=1s 应为帧2, got {(c.red(), c.green())}"
    shutil.rmtree(d, ignore_errors=True)


def cleanup():
    if os.path.isdir(TMP):
        shutil.rmtree(TMP)


def test_frame_playback_and_oneshot():
    colors = [(i * 16, 0, 255 - i * 16) for i in range(16)]
    r = setup_renderer(os.path.join(TMP, "s1"), {"idle": colors, "done": colors})
    fired = {"n": 0}
    r.set_oneshot_callback(lambda: fired.__setitem__("n", fired["n"] + 1))
    r.set_size(256, 256, 1.0)

    # idle 是循环：t=0 帧颜色 = colors[0]
    r.set_state("idle"); r._t = 0.0
    img = QImage(256, 256, QImage.Format_RGBA8888); img.fill(0)
    p = QPainter(img); r.paint(p); p.end()
    assert center_color(img) == colors[0], f"t=0 应显示第1帧, got {center_color(img)}"

    # t=0.5s @80ms/帧 → 第 6 帧
    r._t = 0.5
    img = QImage(256, 256, QImage.Format_RGBA8888); img.fill(0)
    p = QPainter(img); r.paint(p); p.end()
    assert center_color(img) == colors[6], f"t=0.5 应显示第7帧, got {center_color(img)}"

    # done 是 one-shot：播完 16 帧后由 tick 触发回调一次（paint 不再触发），停在最后一帧
    r.set_state("done"); r._t = 0.0
    assert not fired["n"]
    img = QImage(256, 256, QImage.Format_RGBA8888); img.fill(0)
    r._t = 5.0
    p = QPainter(img); r.paint(p); p.end()
    assert fired["n"] == 0, "离屏 paint（如锚点扫描）不得触发 one-shot 回调"
    r.tick(0.0)
    assert fired["n"] == 1, "one-shot 播完应触发一次回调"
    assert center_color(img) == colors[15], "one-shot 结束应停在最后一帧"
    r.tick(4.0)
    assert fired["n"] == 1, "不应重复触发"
    # 同名 one-shot 再次请求：从头播并能再次触发（此前会卡在末帧）
    r.set_state("done")
    assert r._t == 0.0
    r.tick(5.0)
    assert fired["n"] == 2


def test_fallback_chain():
    """回退链（帧序列版）：有专属帧序列用专属；无则回退到 SPRITE_FALLBACK 目标的帧序列首帧。"""
    colors = [(50, 50, 50)] * 16
    # 只有 idle 帧序列：dragging（映射到 idle）回退显示 idle 首帧
    r = setup_renderer(os.path.join(TMP, "s2"), {"idle": colors})
    r.set_size(256, 256, 1.0)
    r.set_state("dragging")
    img = QImage(256, 256, QImage.Format_RGBA8888); img.fill(0)
    p = QPainter(img); r.paint(p); p.end()
    assert center_color(img) == colors[0], "dragging 无帧序列应回退 idle"
    # 非映射状态（sleeping）缺失时同样回退 idle 首帧
    r.set_state("sleeping")
    img = QImage(256, 256, QImage.Format_RGBA8888); img.fill(0)
    p = QPainter(img); r.paint(p); p.end()
    assert center_color(img) == colors[0], "sleeping 无帧序列应回退 idle"

    # 无任何帧序列：构造即抛错（make_renderer 会捕获并回退静态渲染器）
    empty = os.path.join(TMP, "s3")
    os.makedirs(empty, exist_ok=True)
    try:
        SpriteSheetRenderer(empty)
    except RuntimeError:
        pass
    else:
        raise AssertionError("空素材目录应抛 RuntimeError")


if __name__ == "__main__":
    test_frame_playback_and_oneshot()
    test_fallback_chain()
    test_default_durations_table()
    test_frames_dir_playback()
    cleanup()
    print("SpriteSheetRenderer 测试通过 ✔")
