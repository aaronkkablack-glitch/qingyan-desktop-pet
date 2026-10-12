"""皮卡鱼规则子程序适配。仅裁决，不提供走棋/棋力搜索。"""
import os
import subprocess
import sys
from pathlib import Path

REVISION = "d3adf358ce3dc6d68d9caf2cba338a455a4654d7"

def executable():
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    return root/"rules_bridge"/"judge.exe"

def fen(board, turn, clock=0):
    rows = []
    for row in board:
        text, empty = "", 0
        for piece in row:
            if piece == ".": empty += 1
            else:
                if empty: text += str(empty); empty = 0
                text += piece
        if empty: text += str(empty)
        rows.append(text)
    return "/".join(rows) + (" w" if turn == 0 else " b") + f" - - {min(clock,119)} 1"

def coordinate(move):
    return "".join(chr(97+c)+str(9-r) for r,c in move)

def judge(start_fen, moves):
    if "\n" in start_fen or "\t" in start_fen:
        raise ValueError("非法 FEN 分隔符")
    payload = start_fen + "\t" + " ".join(moves) + "\n"
    last = None
    for _ in range(2):   # 杀软首次扫描 / 机器瞬时卡顿导致的超时或进程被拦：重试一次再认输
        try:
            result = subprocess.run([str(executable())], input=payload, text=True, encoding="utf-8",
                capture_output=True, timeout=3, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        except subprocess.TimeoutExpired:
            # 不是 OSError/RuntimeError/ValueError 的子类：不转换会逃出 Qt 槽，让棋局卡死
            last = RuntimeError("规则裁决超时")
            continue
        output = result.stdout.strip()
        if result.returncode or output not in ("ongoing","draw","red","black"):
            last = RuntimeError("规则裁决失败：" + (output or result.stderr)[:200])
            if "Invalid" in (output or result.stderr):
                raise last   # FEN/着法本身非法：重试无意义
            continue
        return output
    raise last

def game_result(game):
    if game.rule_start_fen is None:
        return judge(fen(game.board, game.turn), [])
    return judge(game.rule_start_fen, game.rule_moves)
