# -*- coding: utf-8 -*-
"""发丝白边清理器（defringe）：把 alpha 边缘带的像素颜色替换为最近不透明前景色。

用法: python 清理白边.py [目录] （默认 静态图/，处理所有 *-sheet*.png，原文件备份到 _original/）
原理: 业内标准 defringe——抗锯齿边缘像素是前景与背景的混合色，删除背景后残留白色；
     将边缘带（距不透明前景 ≤band 像素）的 RGB 替换为最近前景像素的颜色，alpha 不动。
"""
import os
import sys
import shutil
from collections import deque

import numpy as np
from PIL import Image

BAND = 2  # 边缘净化带宽（像素）


def defringe(rgba: np.ndarray, band: int = BAND) -> np.ndarray:
    a = rgba.copy()
    h, w = a.shape[:2]
    alpha = a[..., 3]
    opaque = alpha >= 250
    # 距离场 + 最近前景源（BFS 分层扩散）
    dist = np.full((h, w), 127, np.uint16)
    src = np.zeros((h, w, 2), np.int32)
    q = deque()
    ys, xs = np.nonzero(opaque)
    for y, x in zip(ys.tolist(), xs.tolist()):
        dist[y, x] = 0
        src[y, x] = (y, x)
        q.append((y, x))
    while q:
        y, x = q.popleft()
        d = dist[y, x]
        if d >= band:
            continue
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and dist[ny, nx] > d + 1:
                dist[ny, nx] = d + 1
                # 继承"最近前景"：自身是前景则继承自己，否则继承传播来源
                src[ny, nx] = src[y, x]
                q.append((ny, nx))
    # 边缘带内非前景像素：RGB 替换为最近前景色，alpha 保持
    ys, xs = np.nonzero((dist > 0) & (dist <= band))
    sy, sx = src[ys, xs, 0], src[ys, xs, 1]
    a[ys, xs, 0] = a[sy, sx, 0]
    a[ys, xs, 1] = a[sy, sx, 1]
    a[ys, xs, 2] = a[sy, sx, 2]
    return a


def process_file(path: str, backup_dir: str | None):
    im = Image.open(path).convert('RGBA')
    arr = np.asarray(im).copy()
    before = arr.copy()
    out = defringe(arr)
    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        shutil.copy2(path, os.path.join(backup_dir, os.path.basename(path)))
    Image.fromarray(out).save(path)
    changed = int((np.abs(out[..., :3].astype(int) - before[..., :3].astype(int)).max(axis=2) > 6).sum())
    print(f'  {os.path.basename(path)}: 修改 {changed} 像素 ({changed / (out.shape[0] * out.shape[1]):.1%})')


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '静态图')
    backup = os.path.join(target, '_original')
    files = [f for f in os.listdir(target) if 'sheet' in f and f.endswith('.png')]
    print(f'处理 {len(files)} 张 sheet（原文件备份到 {backup}/）')
    for f in sorted(files):
        process_file(os.path.join(target, f), backup)
    print('完成')
