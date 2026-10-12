"""本地性能基线，输出测量结果；不把机器相关耗时作为测试通过条件。"""
import os
import sys
import time
import statistics
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter
from pet.animation import SpriteSheetRenderer
from pet.config import DEFAULTS
from pet.games.xiangqi_engine import Game, ai_move
app = QApplication([])
r = SpriteSheetRenderer(DEFAULTS["sprite_assets_dir"])
r.set_size(400,400,1)
image = QImage(400,400,QImage.Format_ARGB32_Premultiplied)
samples=[]
for i in range(240):
    r.tick(0.033)
    p=QPainter(image)
    begin=time.perf_counter()
    r.paint(p)
    samples.append((time.perf_counter()-begin)*1000)
    p.end()
print("sprite paint median_ms=%.3f p95_ms=%.3f cached_frames=%d" % (
    statistics.median(samples), sorted(samples)[int(len(samples)*.95)], len(r._scaled)))
for level in (0,1,2):
    game=Game()
    begin=time.perf_counter()
    move=ai_move(game,level)
    print("xiangqi level=%d elapsed_s=%.3f legal=%s" % (
        level,time.perf_counter()-begin,move in game.legal_moves(game.turn)))
