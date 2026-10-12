# 动效可行性样张：呼吸浮动 + 发丝摆动（纯代码，无外部工具）
# 用法: python poc_animate.py [图片路径]
import sys, os
import numpy as np
from PIL import Image

src_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join('GLM形象参考图', '少女.png')
out_dir = os.path.dirname(os.path.abspath(src_path))
name = os.path.splitext(os.path.basename(src_path))[0]

src = Image.open(src_path).convert('RGBA')
arr = np.asarray(src).astype(np.float32)
H, W = arr.shape[:2]

FRAMES = 40
BOB_AMP = 4.0      # 呼吸上下浮动幅度（像素）
SWAY_AMP = 7.0     # 发丝摆动幅度（像素）
ANCHOR_Y = int(H * 0.14)  # 摆动锚点：头顶（头发固定处）
HAIR_Y_LIMIT = float(sys.argv[2]) if len(sys.argv) > 2 else 0.72  # 此线以下（裙摆/鞋）不参与摆动

ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
cx = W / 2.0
# 越靠身体两侧移动越多（中间躯干保持不动）
edge_w = np.clip(np.abs(xs - cx) / (W * 0.5), 0, 1) ** 1.6
# 距离锚点越远（发梢方向）摆动越大
len_w = np.clip((ys - ANCHOR_Y) / (H - ANCHOR_Y), 0, 1) ** 1.2
# 只让"深色头发"区域摆动：亮度掩膜 + 高斯羽化，避免裙摆被吹动
rgb = arr[..., :3]
luma = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
dark = ((luma < 95) & (arr[..., 3] > 40)).astype(np.float32)
mask_img = Image.fromarray((dark * 255).astype(np.uint8)).filter(
    __import__('PIL.ImageFilter', fromlist=['GaussianBlur']).GaussianBlur(7))
hair_w = np.asarray(mask_img).astype(np.float32) / 255.0
hair_w *= np.clip((HAIR_Y_LIMIT - ys / H) / 0.15 + 1, 0, 1)  # 底部渐出

frames_rgba = []
for i in range(FRAMES):
    t = i / FRAMES * 2 * np.pi
    dy = BOB_AMP * np.sin(t)                                    # 整体呼吸
    dx = SWAY_AMP * len_w * edge_w * hair_w * np.sin(t * 0.5 + ys / 90.0)  # 自上而下的行波
    sx = np.clip(xs + dx, 0, W - 1)
    sy = np.clip(ys + dy, 0, H - 1)
    x0 = np.floor(sx).astype(np.int32); y0 = np.floor(sy).astype(np.int32)
    x1 = np.minimum(x0 + 1, W - 1);     y1 = np.minimum(y0 + 1, H - 1)
    fx = (sx - x0)[..., None]; fy = (sy - y0)[..., None]
    out = (arr[y0, x0] * (1 - fx) * (1 - fy) + arr[y0, x1] * fx * (1 - fy)
           + arr[y1, x0] * (1 - fx) * fy + arr[y1, x1] * fx * fy)
    frames_rgba.append(out.astype(np.uint8))

def on_white(rgba):
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    rgb = rgba[..., :3].astype(np.float32) * a + 255.0 * (1 - a)
    return rgb.astype(np.uint8)

# 1) 导出 GIF（白底，供直接查看）
gif_frames = [Image.fromarray(on_white(f)).quantize(colors=128) for f in frames_rgba]
gif_path = os.path.join(out_dir, f'{name}_动效样张.gif')
gif_frames[0].save(gif_path, save_all=True, append_images=gif_frames[1:],
                   duration=70, loop=0, disposal=2)

# 2) 导出联排对照图（一图看全程动作，供静态审阅）
cols, rows = 5, 4
small = [Image.fromarray(on_white(f)).resize((W // 2, H // 2)) for f in frames_rgba]
sw, sh = W // 2, H // 2
sheet = Image.new('RGB', (cols * sw, rows * sh), 'white')
for i, im in enumerate(small):
    sheet.paste(im, ((i % cols) * sw, (i // cols) * sh))
sheet_path = os.path.join(out_dir, f'{name}_动效联排.png')
sheet.save(sheet_path)
print('GIF:', gif_path)
print('联排:', sheet_path)
