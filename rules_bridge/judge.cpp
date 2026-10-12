// SPDX-License-Identifier: GPL-3.0-or-later
// Qingyan rule-only adapter. No search, evaluation network or UCI engine loop.
#include "position.h"
#include "movegen.h"
#include "attacks.h"
#include <iostream>
#include <sstream>
#include <deque>
using namespace Stockfish;
int main() {
    Attacks::init(); Position::init();
    std::string line;
    while (std::getline(std::cin, line)) {
        try {
            const auto split = line.find('\t');
            if (split == std::string::npos) throw std::runtime_error("missing separator");
            std::deque<StateInfo> states(1);
            Position position;
            if (auto error = position.set(line.substr(0, split), &states.back()))
                throw std::runtime_error(error->what());
            std::istringstream moves(line.substr(split+1));
            std::string token;
            while (moves >> token) {
                if (token.size()!=4 || token[0]<'a' || token[0]>'i' || token[2]<'a' || token[2]>'i'
                    || token[1]<'0' || token[1]>'9' || token[3]<'0' || token[3]>'9')
                    throw std::runtime_error("bad move");
                Move move(make_square(File(token[0]-'a'), Rank(token[1]-'0')),
                          make_square(File(token[2]-'a'), Rank(token[3]-'0')));
                if (!MoveList<LEGAL>(position).contains(move)) throw std::runtime_error("illegal move");
                states.emplace_back(); position.do_move(move, states.back());
            }
            Value result;
            if (MoveList<LEGAL>(position).size()==0) result = -1;
            else if (!position.rule_judge(result, 0)) { std::cout << "ongoing\n" << std::flush; continue; }
            std::cout << (result==VALUE_DRAW ? "draw" :
                ((result>0)==(position.side_to_move()==WHITE) ? "red" : "black")) << '\n' << std::flush;
        } catch (const std::exception& error) {
            std::cout << "error " << error.what() << '\n' << std::flush;
        }
    }
}
