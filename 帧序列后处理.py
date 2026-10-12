# -*- coding: utf-8 -*-
"""帧序列后处理：
1) 绿残留清除：对"绿优势且邻接透明区"的像素去绿（G←(R+B)/2），强绿直接置透明；
2) sleeping 缩小：帧内容以 bbox 中心为轴统一缩放 0.85，脚底线保持。
用法: python 帧序列后处理.py（备份到 帧序列/_pre_fix/）
"""
import os
import shutil
from collections import deque

import numpy as np
from PIL import Image

ROOT = '静态图/帧序列'
BACKUP = '静态图/_pre_fix'


def has_transparent_neighbor(alpha, y, x, r=3):
    h, w = alpha.shape
    y0, y1 = max(0, y - r), min(h, y + r + 1)
    x0, x1 = max(0, x - r), min(w, x + r + 1)
    return (alpha[y0:y1, x0:x1] < 10).any()


def clean_green(rgba):
    a = rgba.copy()
    alpha = a[..., 3]
    r, g, b = a[..., 0].astype(int), a[..., 1].astype(int), a[..., 2].astype(int)
    greenish = (alpha > 0) & (g - r > 25) & (g - b > 25)
    strong = greenish & (g - np.maximum(r, b) > 70)
    h, w = alpha.shape
    # 邻接透明区才处理（保护角色内部绿色装饰）
    ys, xs = np.nonzero(greenish)
    for y, x in zip(ys, xs):
        if strong[y, x] or has_transparent_neighbor(alpha, y, x, 3):
            if strong[y, x]:
                a[y, x, 3] = 0
            else:
                a[y, x, 1] = (r[y, x] + b[y, x]) // 2  # 去绿
    return a, int(greenish.sum())


def scale_content(rgba, factor=0.85):
    """以内容 bbox 中心为轴缩放整帧内容，保持画布尺寸与脚底位置。"""
    a = rgba.copy()
    alpha = a[..., 3]
    ys, xs = np.nonzero(alpha > 10)
    if len(ys) == 0:
        return a
    cx = (xs.min() + xs.max()) / 2
    by = ys.max()
    h, w = a.shape[:2]
    src = Image.fromarray(a)
    nw, nh = int(w * factor), int(h * factor)
    scaled = src.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    # 缩放后脚底位置 = by * factor；贴回原 by 位置（脚底不动）
    paste_y = int(by * factor)
    canvas.paste(scaled, (int((w - nw) / 2), paste_y - nh + (h - 1 - by) * 0), None)
    # 脚底对齐：scaled 的脚底在其内部 y = by*factor 处（因为整帧等比缩放），目标是画布 by 处
    # 精确：内容脚底在 scaled 内的 y = by*factor；希望其落在画布 by
    off_y = int(by - by * factor)
    canvas = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    canvas.paste(scaled, (int((w - nw) / 2), off_y), scaled)
    return np.asarray(canvas).copy()


if __name__ == '__main__':
    os.makedirs(BACKUP, exist_ok=True)
    # 1) 全状态绿残留清理
    for state in sorted(os.listdir(ROOT)):
        d = os.path.join(ROOT, state)
        if not os.path.isdir(d):
            continue
        files = sorted(f for f in os.listdir(d) if f.endswith('.png'))
        total = 0
        for f in files:
            p = os.path.join(d, f)
            bak = os.path.join(BACKUP, state, f)
            os.makedirs(os.path.dirname(bak), exist_ok=True)
            if not os.path.exists(bak):
                shutil.copy2(p, bak)
            a = np.asarray(Image.open(p).convert('RGBA')).copy()
            a2, n = clean_green(a)
            total += n
            Image.fromarray(a2).save(p)
        print(f'{state}: 清绿 {total} px')
    # 2) sleeping 缩小 0.85（备份同目录已含）
    d = os.path.join(ROOT, 'sleeping')
    for f in sorted(os.listdir(d)):
        if not f.endswith('.png'):
            continue
        p = os.path.join(d, f)
        bak = os.path.join(BACKUP, 'sleeping', f)
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        a = np.asarray(Image.open(p).convert('RGBA')).copy()
        Image.fromarray(scale_content(a, 0.85)).save(p)
    print('sleeping 已缩放 0.85')
    print('完成（备份在', BACKUP, '/）')
