# 清言规则裁决子程序

采用 Pikafish 提交 d3adf358ce3dc6d68d9caf2cba338a455a4654d7 的程序棋规。
judge.cpp 与修改后的 position_rules.cpp 按 GPL-3.0-or-later 分发。
pikafish-source.zip 是该提交完整源码，包含 Copying.txt 与 AUTHORS。
不包含搜索、棋力评估网络或 UCI 引擎入口；清言继续使用 Python AI。

重建：解压源码，使用 Zig 0.16.0 的 c++ 编译器；build.py 要求 git rev-parse HEAD
匹配提交；使用随包源码zip时直接构建，不需要初始化git。
实际命令由 build.py 给出，编译 position_rules.cpp、movegen.cpp、attacks.cpp、
bitboard.cpp、nnue/features/half_ka_v2_hm.cpp 和 judge.cpp，-std=c++17 -O2
-DNDEBUG -DIS_64BIT。修改仅移除缓存预取、调试坐标依赖；棋规判断逻辑未修改。

协议：每行“起始完整FEN\t空格分隔走子历史”，输出 ongoing/draw/red/black/error。
规则出处：https://pikafish.org/rule.html
上游：https://github.com/official-pikafish/Pikafish
