# Instructions

Pick the best hand(s) from a list of poker hands.

See [Wikipedia][poker-hands] for an overview of poker hands.

[poker-hands]: https://en.wikipedia.org/wiki/List_of_poker_hands

## Interface

`BestHand(hands []string) ([]string, error)` takes one or more hands and returns the winning hands.

- A hand is a string of five cards separated by single spaces, for example `"4♤ 5♤ 7♡ 8♢ J♧"`.
- A card is its rank followed by its suit. The ranks are `2` to `10`, `J`, `Q`, `K` and `A`. The suits are `♤`, `♡`, `♢` and `♧`.
- Each returned hand is the input string, unchanged. With one hand, that hand wins.
- When hands tie for the best, all of them are returned, in the same order as in the input.
- An ace can end a straight (`10 J Q K A`) or start one (`A 2 3 4 5`), but it cannot be in the middle (`Q K A 2 3`). `A 2 3 4 5` is the lowest straight.
- For valid hands, the error is `nil`. When any hand is not valid, `BestHand` returns a non-nil error. A hand is not valid when it has fewer or more than five cards, when a card has no rank, an unknown rank (such as `1` or `11`), no suit, an unknown suit (such as `H` or `♥`) or more than one suit, or when two cards are not separated by a space.

Implement the solution in `poker.go`. Keep the exported names and signatures as they are. Tests that you cannot see will check your solution.
