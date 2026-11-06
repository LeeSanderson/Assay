# Instructions

Pick the best hand(s) from a list of poker hands.

See [Wikipedia][poker-hands] for an overview of poker hands.

[poker-hands]: https://en.wikipedia.org/wiki/List_of_poker_hands

## Interface

`bestHands(hands)` takes an array of one or more hands and returns an array of the winning hands.

- A hand is a string of five cards separated by single spaces, for example `"4S 5S 7H 8D JC"`.
- A card is its rank followed by its suit. The ranks are `2` to `10`, `J`, `Q`, `K` and `A`. The suits are `S`, `H`, `D` and `C`.
- Each returned hand is the input string, unchanged. With one hand, that hand wins.
- When hands tie for the best, all of them are returned, in the same order as in the input.
- An ace can end a straight (`10 J Q K A`) or start one (`A 2 3 4 5`), but it cannot be in the middle (`Q K A 2 3`). `A 2 3 4 5` is the lowest straight.

Implement the solution in `poker.ts`. Keep the exported names and signatures as they are. Tests that you cannot see will check your solution.
