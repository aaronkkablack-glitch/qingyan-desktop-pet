"""实际规则子程序官方棋例与历史重放，不启动棋力引擎。"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pet.xiangqi_rules import judge, fen, coordinate
from pet.games.xiangqi_engine import Game

def test_official_examples():
    cases = [
      ("4k4/9/2c2an2/4c4/6R2/9/9/4B4/4A4/3K1AB2 w - - 0 1",
       "g5e5 f7e8 e5g5 e8f7 g5e5 f7e8 e5g5 e8f7", "draw"),
      ("3k5/2R6/9/9/9/9/9/9/6r2/4K1N2 w - - 0 1",
       "c8c9 d9d8 c9c8 d8d9 c8c9 d9d8 c9c8 d8d9", "black"),
      ("3a1kb2/4a4/4r3b/7c1/9/9/9/8R/7CC/3K5 w - - 0 1",
       "i2h2 h6i6 h2i2 i6h6 i2h2 h6i6 h2i2 i6h6", "black")]
    for start, moves, expected in cases:
        assert judge(start,moves.split()) == expected
        assert judge(start,moves.split()[:2]) == "ongoing"
    game=Game()
    assert judge(fen(game.board,game.turn),[]) == "ongoing"
    assert coordinate(((9,1),(7,2))) == "b0c2"

if __name__ == "__main__":
    test_official_examples()
    print("Pikafish rule-only tests passed")
