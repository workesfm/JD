"""Independent enumeration of induced-path and induced-cycle polyhexes.

Grow only connected cell graphs of maximum degree two. Every induced path can
lose an endpoint to give a smaller path; every cycle can lose a vertex to give
a path. Thus extending paths and closing their endpoints is exhaustive. Free
objects are reduced under translations and the twelve hexagonal symmetries.
"""
import json

DIRECTIONS = ((1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1))


def rotate(points):
    return tuple((-r, q + r) for q, r in points)


def normalized(points):
    minimum_q = min(q for q, _ in points)
    minimum_r = min(r for _, r in points)
    return tuple(sorted((q - minimum_q, r - minimum_r) for q, r in points))


def canonical(points):
    orientations = []
    for reflected in (False, True):
        image = tuple((r, q) if reflected else (q, r) for q, r in points)
        for _ in range(6):
            orientations.append(normalized(image))
            image = rotate(image)
    return min(orientations)


def enumerate_paths_and_rings(maximum):
    paths = {((0, 0),)}
    path_counts, ring_counts = [1], [0]
    for size in range(2, maximum + 1):
        next_paths, rings = set(), set()
        for shape in paths:
            occupied = set(shape)
            endpoints = set()
            for q, r in shape:
                degree = sum((q + dq, r + dr) in occupied for dq, dr in DIRECTIONS)
                if degree <= 1:
                    endpoints.add((q, r))
            assert len(endpoints) == (1 if len(shape) == 1 else 2)
            candidates = {(q + dq, r + dr) for q, r in endpoints for dq, dr in DIRECTIONS} - occupied
            for q, r in candidates:
                touching = {(q + dq, r + dr) for dq, dr in DIRECTIONS} & occupied
                if not touching or len(touching) > 2 or not touching.issubset(endpoints):
                    continue
                child = canonical(shape + ((q, r),))
                if len(touching) == 1:
                    next_paths.add(child)
                else:
                    rings.add(child)
        paths = next_paths
        path_counts.append(len(paths))
        ring_counts.append(len(rings))
    return path_counts, ring_counts


def self_test():
    # Independent cube-distance definition checks that our6moves are neighbors.
    assert all((abs(q) + abs(r) + abs(q + r)) // 2 == 1 for q, r in DIRECTIONS)
    image = DIRECTIONS
    for _ in range(6):
        assert set(image) == set(DIRECTIONS)
        image = rotate(image)
    assert {(r, q) for q, r in DIRECTIONS} == set(DIRECTIONS)
    sample = ((0, 0), (1, 0), (2, -1), (3, -1))
    base = canonical(sample)
    image = sample
    for _ in range(6):
        assert canonical(image) == base
        assert canonical(tuple((r, q) for q, r in image)) == base
        image = rotate(image)
    assert canonical(tuple((q + 8, r - 13) for q, r in sample)) == base
    assert enumerate_paths_and_rings(3) == ([1, 1, 2], [0, 0, 1])


def main():
    self_test()
    paths, rings = enumerate_paths_and_rings(13)
    print(json.dumps({'claim': 15, 'range': [1, 13], 'scope': 'full stated range',
                      'R6': rings, 'path_side_condition_A003104': paths,
                      'hex_symmetries': 12, 'holes_allowed': True,
                      'independent_geometric_self_tests_passed': True}, indent=2))


if __name__ == '__main__':
    main()
