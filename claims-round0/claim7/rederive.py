"""Enumerate free9-ominoes and their knight-tour orbits independently.

Connected square-cell sets are grown one cell at a time and reduced by D4.
Knight paths are exhaustively generated, then canonicalized under reversal
and the actual geometric stabilizer of each board. No reference counts enter
the calculation, and no claimant implementation or external library is used.
"""
from collections import Counter
import json

SIDES = ((1, 0), (-1, 0), (0, 1), (0, -1))
KNIGHT = ((1, 2), (1, -2), (-1, 2), (-1, -2),
          (2, 1), (2, -1), (-2, 1), (-2, -1))


def transform(shape, swap, sx, sy):
    points = [(sx * (y if swap else x), sy * (x if swap else y)) for x, y in shape]
    ax, ay = min(x for x, _ in points), min(y for _, y in points)
    return tuple((x - ax, y - ay) for x, y in points)


def canonical(shape):
    return min(tuple(sorted(transform(shape, swap, sx, sy)))
               for swap in (False, True) for sx in (-1, 1) for sy in (-1, 1))


def free_boards(n):
    shapes = {((0, 0),)}
    counts = [1]
    for _ in range(1, n):
        following = set()
        for shape in shapes:
            occupied = set(shape)
            boundary = {(x + dx, y + dy) for x, y in shape for dx, dy in SIDES} - occupied
            for point in boundary:
                following.add(canonical(shape + (point,)))
        shapes = following
        counts.append(len(shapes))
    return shapes, counts


def tour_orbits(shape):
    count = len(shape)
    index = {p: i for i, p in enumerate(shape)}
    neighbors = []
    for x, y in shape:
        mask = 0
        for dx, dy in KNIGHT:
            j = index.get((x + dx, y + dy))
            if j is not None:
                mask |= 1 << j
        neighbors.append(mask)
    full = (1 << count) - 1
    seen, frontier = 0, 1
    while frontier:
        bit = frontier & -frontier
        frontier ^= bit
        if seen & bit:
            continue
        seen |= bit
        frontier |= neighbors[bit.bit_length() - 1] & ~seen
    if seen != full:
        return set(), 0
    if abs(sum(1 if (x + y) % 2 else -1 for x, y in shape)) > 1:
        return set(), 0
    leaves = [i for i, mask in enumerate(neighbors) if mask.bit_count() == 1]
    if len(leaves) > 2:
        return set(), 0

    automorphisms = []
    for swap in (False, True):
        for sx in (-1, 1):
            for sy in (-1, 1):
                image = transform(shape, swap, sx, sy)
                if tuple(sorted(image)) == shape:
                    automorphisms.append(tuple(index[p] for p in image))
    assert automorphisms
    orbits = set()
    path = []

    def visit(current, used, start):
        path.append(current)
        if used == full:
            # With a leaf we fix that endpoint. Otherwise discard reversals.
            if leaves or start < current:
                images = []
                for permutation in automorphisms:
                    mapped = tuple(permutation[i] for i in path)
                    images.extend((mapped, mapped[::-1]))
                orbits.add(min(images))
        else:
            candidates = neighbors[current] & ~used
            while candidates:
                bit = candidates & -candidates
                candidates ^= bit
                visit(bit.bit_length() - 1, used | bit, start)
        path.pop()

    starts = leaves[:1] if leaves else range(count)
    for start in starts:
        visit(start, 1 << start, start)
    return orbits, len(automorphisms)


def main():
    sample = ((0, 0), (1, 0), (1, 1), (2, 1))
    base = canonical(sample)
    for swap in (False, True):
        for sx in (-1, 1):
            for sy in (-1, 1):
                assert canonical(transform(sample, swap, sx, sy)) == base
    assert canonical(tuple((x + 19, y - 7) for x, y in sample)) == base

    boards, free_counts = free_boards(9)
    distribution, frame_distribution, frame_4x4 = Counter(), {}, Counter()
    details = []
    for board in sorted(boards):
        orbits, stabilizer = tour_orbits(board)
        if not orbits:
            continue
        tours = len(orbits)
        width, height = sorted((max(x for x, _ in board) + 1, max(y for _, y in board) + 1))
        frame = str(width) + 'x' + str(height)
        distribution[tours] += 1
        entry = frame_distribution.setdefault(frame, {'boards': 0, 'tours': 0})
        entry['boards'] += 1
        entry['tours'] += tours
        if frame == '4x4':
            frame_4x4[tours] += 1
        details.append({'cells': board, 'tour_orbits': tours, 'geometric_stabilizer_order': stabilizer,
                        'bounding_box': frame})
    result = {'claim': 7, 'free_polyomino_counts_n_1_through_9': free_counts,
              'tourable_boards': len(details), 'geometric_tours': sum(x['tour_orbits'] for x in details),
              'boards_by_tour_count': dict(sorted(distribution.items())),
              'bounding_boxes': dict(sorted(frame_distribution.items())),
              'frame_4x4_boards_by_tour_count': dict(sorted(frame_4x4.items())),
              'canonical_boards': details}
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
