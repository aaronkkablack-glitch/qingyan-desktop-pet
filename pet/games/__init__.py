# -*- coding: utf-8 -*-
"""内置游戏（固定四个，不再扩充）：随程序/exe 一起分发，开箱即玩。
菜单顺序即 BUILTIN_GAMES 顺序（象棋在斗地主上面）。外部扩展游戏放 互动插件/ 目录。

每个游戏模块遵守与插件相同的协议：TITLE / DESCRIPTION / create(cfg, parent)。
"""
from . import doudizhu, gomoku, tictactoe, xiangqi

BUILTIN_GAMES = (tictactoe, gomoku, xiangqi, doudizhu)
