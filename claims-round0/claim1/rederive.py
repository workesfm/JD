"""Independently count the claim's minimum n=1..12, using only stdlib.

State: used values and the three least possible increasing-subsequence
endpoints. Fixed points are refused at their position; a fourth pile is
refused. Different prefixes sharing a state have the same valid suffixes.
"""
from functools import lru_cache
from itertools import combinations, permutations
import json


def count_avoiding_derangements(n):
    full = (1 << n) - 1
    infinity = n + 1

    @lru_cache(maxsize=None)
    def suffixes(used, a, b, c):
        if used == full:
            return 1
        position = used.bit_count() + 1
        available = full ^ used
        total = 0
        while available:
            bit = available & -available
            available ^= bit
            value = bit.bit_length()
            if value == position:
                continue
            if value < a:
                total += suffixes(used | bit, value, b, c)
            elif value < b:
                total += suffixes(used | bit, a, value, c)
            elif value < c:
                total += suffixes(used | bit, a, b, value)
            # Otherwise appending value creates an increasing subsequence of4.
        return total

    count = suffixes(0, infinity, infinity, infinity)
    states = suffixes.cache_info().currsize
    suffixes.cache_clear()
    return count, states


def literal_small_count(n):
    quadruples = tuple(combinations(range(n), 4))
    total = 0
    for p in permutations(range(1, n + 1)):
        if any(value == i + 1 for i, value in enumerate(p)):
            continue
        if not any(p[i] < p[j] < p[k] < p[l] for i, j, k, l in quadruples):
            total += 1
    return total


def main():
    # A separate literal definition, not patience sorting, checks small cases.
    for n in range(8):
        assert count_avoiding_derangements(n)[0] == literal_small_count(n)
    terms, states = [], []
    for n in range(1, 13):
        value, size = count_avoiding_derangements(n)
        terms.append(value)
        states.append(size)
    print(json.dumps({'claim': 1, 'range': [1, 12], 'scope': 'stated minimum only',
                      'terms': terms, 'memo_states_per_n': states,
                      'literal_crosscheck_n_0_through_7': True,
                      'terms_13_through_24_evaluated': False}, indent=2))


if __name__ == '__main__':
    main()
