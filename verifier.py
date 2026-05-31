"""CAISc-faithful Connected Still Life verifier.

Mirrors the official grader exactly:
(1) grid is n x n with entries in {0,1};
(2) every live cell has exactly 2 or 3 live neighbors (Moore/8);
(3) no dead cell -- inside the box OR in its one-cell exterior ring --
    has exactly 3 live neighbors (no births);
(4) all live cells are 8-connected (BFS);
(5) claimed_cells equals the actual live count.
"""
from collections import deque

NB = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]


def live_neighbors(grid, n, i, j):
    c = 0
    for di, dj in NB:
        ii, jj = i + di, j + dj
        if 0 <= ii < n and 0 <= jj < n and grid[ii][jj] == 1:
            c += 1
    return c


def verify(grid, n, claimed=None):
    # (1) shape / binary
    if len(grid) != n:
        return False, f"grid has {len(grid)} rows, expected {n}"
    for r, row in enumerate(grid):
        if len(row) != n:
            return False, f"row {r} has {len(row)} cols, expected {n}"
        for v in row:
            if v not in (0, 1):
                return False, f"non-binary entry {v!r}"

    live = [(i, j) for i in range(n) for j in range(n) if grid[i][j] == 1]
    count = len(live)

    # (5) count match (only if a claim is supplied)
    if claimed is not None and count != claimed:
        return False, f"claimed {claimed} != actual {count}"

    # (2) stability: live cells need 2 or 3 live neighbors
    for (i, j) in live:
        k = live_neighbors(grid, n, i, j)
        if k not in (2, 3):
            return False, f"unstable live cell at {(i,j)} has {k} live neighbors"

    # (3) no births, INCLUDING the one-cell exterior ring (indices -1..n)
    for i in range(-1, n + 1):
        for j in range(-1, n + 1):
            in_box = 0 <= i < n and 0 <= j < n
            if in_box and grid[i][j] == 1:
                continue  # live cell, not a candidate for birth
            if live_neighbors(grid, n, i, j) == 3:
                where = "interior" if in_box else "exterior-ring"
                return False, f"birth at {where} dead cell {(i,j)} (exactly 3 live neighbors)"

    # (4) 8-connectivity via BFS
    if count > 1:
        liveset = set(live)
        seen = {live[0]}
        dq = deque([live[0]])
        while dq:
            i, j = dq.popleft()
            for di, dj in NB:
                nb = (i + di, j + dj)
                if nb in liveset and nb not in seen:
                    seen.add(nb)
                    dq.append(nb)
        if len(seen) != count:
            return False, f"disconnected: reached {len(seen)} of {count} live cells"

    return True, f"VALID connected still life, {count} live cells"


if __name__ == "__main__":
    # golden tests against tiny known still lifes
    def box(rows):
        return [[1 if ch == "O" else 0 for ch in r] for r in rows]

    # Block (2x2) inside a 4x4 box -> valid, 4 cells
    block = box([
        "....",
        ".OO.",
        ".OO.",
        "....",
    ])
    print("block 4x4:", verify(block, 4, 4))

    # Beehive inside a 5x6 box -> valid, 6 cells
    beehive = box([
        "......",
        "..OO..",
        ".O..O.",
        "..OO..",
        "......",
    ])
    print("beehive 6x5? use n=6 square:")
    beehive6 = box([
        "......",
        "..OO..",
        ".O..O.",
        "..OO..",
        "......",
        "......",
    ])
    print("beehive 6x6:", verify(beehive6, 6, 6))

    # Two separate blocks -> should FAIL connectivity
    two = box([
        "OO...OO",
        "OO...OO",
        ".......",
        ".......",
        ".......",
        ".......",
        ".......",
    ])
    print("two blocks 7x7 (expect disconnected):", verify(two, 7))

    # A single block touching the wall with a stray birth: blinker is NOT a still life
    blinker = box([
        ".....",
        ".....",
        ".OOO.",
        ".....",
        ".....",
    ])
    print("blinker 5x5 (expect unstable/birth):", verify(blinker, 5))
