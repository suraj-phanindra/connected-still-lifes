"""CP-SAT exact engine for connected still life (CAISc 2026, verifiable track).

Mirrors verifier.py semantics EXACTLY:
  (1) grid is n x n, entries in {0, 1};
  (2) every live cell has 2 or 3 live (Moore-8) neighbors;
  (3) NO dead cell -- inside the box OR in its one-cell exterior ring
      (indices -1..n) -- has exactly 3 live (Moore-8) neighbors;
  (4) all live cells are 8-connected;
  (5) claimed_cells equals actual live count.

Connectivity is single-commodity flow (SCF):
  - Virtual super-source injects `total_live` units at a single chosen root.
  - Each live cell consumes exactly 1 unit (so all units terminate).
  - Arcs go between 8-adjacent in-box cells; arc-flow is gated on BOTH
    endpoints being live (so flow never crosses dead cells, only live ones).
  - Free root: any live cell can be the root; at most one is. No lex-min
    hard-fix -- the solver picks the most propagation-friendly root.

Objective: maximize sum(live).

Cross-validation contract:
  - Every winning grid round-trips through verifier.verify(grid, n, claimed)
    before being returned to the caller.
  - When solver returns OPTIMAL, the result is mathematically proven optimal;
    when FEASIBLE-but-time-limited, the cells count is a verified lower bound.
"""
from __future__ import annotations

import time
from typing import Iterator

from ortools.sat.python import cp_model

from verifier import verify

# Moore-8 neighborhood offsets (matches verifier.py's NB).
N8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _in_box(i: int, j: int, n: int) -> bool:
    return 0 <= i < n and 0 <= j < n


def _box_nbrs(i: int, j: int, n: int) -> Iterator[tuple[int, int]]:
    for di, dj in N8:
        ii, jj = i + di, j + dj
        if _in_box(ii, jj, n):
            yield (ii, jj)


def solve_cpsat(
    n: int,
    time_limit: float = 120.0,
    workers: int = 4,
    seed: int = 1,
    log_search_progress: bool = False,
    initial_hint: "list[list[int]] | None" = None,
):
    """Solve connected still life on an n x n box via CP-SAT.

    Returns a dict mirroring run_solve.solve_n's shape for easy comparison.

    `initial_hint`, if given, is an n x n 0/1 grid passed to CP-SAT as a
    soft hint via AddHint. CP-SAT biases search toward the hinted values
    but is NOT bound by them -- the search still respects all constraints,
    so the hint does NOT need to be a valid still life.
    """
    M = cp_model.CpModel()
    big_M = n * n                       # safe upper bound on total live cells
    cells = [(i, j) for i in range(n) for j in range(n)]

    # ----- decision variables -----
    live = {c: M.NewBoolVar(f"live_{c[0]}_{c[1]}") for c in cells}
    root = {c: M.NewBoolVar(f"root_{c[0]}_{c[1]}") for c in cells}
    total_live = M.NewIntVar(0, big_M, "total_live")
    M.Add(total_live == sum(live[c] for c in cells))

    # Flow on directed 8-adjacency arcs (both directions per undirected pair).
    flow = {}
    for c in cells:
        for nb in _box_nbrs(c[0], c[1], n):
            flow[(c, nb)] = M.NewIntVar(0, big_M, f"f_{c[0]}_{c[1]}__{nb[0]}_{nb[1]}")

    # Super-source injection at the (unique) root.
    inject = {c: M.NewIntVar(0, big_M, f"inj_{c[0]}_{c[1]}") for c in cells}

    # ----- stability + interior no-birth -----
    # For each cell c, let s = number of live Moore-8 neighbors.
    #   live  -> s in {2, 3}
    #   dead  -> s != 3                 (interior no-birth)
    for c in cells:
        nbr_sum = sum(live[nb] for nb in _box_nbrs(c[0], c[1], n))
        M.Add(nbr_sum >= 2).OnlyEnforceIf(live[c])
        M.Add(nbr_sum <= 3).OnlyEnforceIf(live[c])
        M.Add(nbr_sum != 3).OnlyEnforceIf(live[c].Not())

    # ----- exterior-ring no-birth -----
    # For every cell at index (-1..n, -1..n) that is NOT in the box,
    # the count of in-box live Moore-8 neighbors must NOT equal 3.
    for i in range(-1, n + 1):
        for j in range(-1, n + 1):
            if _in_box(i, j, n):
                continue
            ring_nbrs = []
            for di, dj in N8:
                ii, jj = i + di, j + dj
                if _in_box(ii, jj, n):
                    ring_nbrs.append(live[(ii, jj)])
            if len(ring_nbrs) >= 3:
                M.Add(sum(ring_nbrs) != 3)
            # If <3 in-box neighbors, the count can never reach 3, no constraint needed.

    # ----- root choice -----
    M.Add(sum(root[c] for c in cells) <= 1)
    for c in cells:
        M.AddImplication(root[c], live[c])
    # Force a root to exist iff any cell is live (helps propagation).
    has_live = M.NewBoolVar("has_live")
    M.Add(total_live >= 1).OnlyEnforceIf(has_live)
    M.Add(total_live == 0).OnlyEnforceIf(has_live.Not())
    M.Add(sum(root[c] for c in cells) == 1).OnlyEnforceIf(has_live)
    M.Add(sum(root[c] for c in cells) == 0).OnlyEnforceIf(has_live.Not())

    # ----- arc-flow gating -----
    # f(u,v) > 0 only if BOTH endpoints are live (per user spec).
    for (u, v), fuv in flow.items():
        M.Add(fuv <= big_M * live[u])
        M.Add(fuv <= big_M * live[v])

    # ----- super-source injection at the root -----
    # inject(c) = total_live if root(c) else 0.
    for c in cells:
        M.Add(inject[c] <= big_M * root[c])
        M.Add(inject[c] <= total_live)
        M.Add(inject[c] >= total_live - big_M * (1 - root[c]))

    # ----- flow conservation -----
    # At each cell c: outflow - inflow == inject(c) - live(c).
    # Equivalently: inflow + inject(c) == outflow + live(c).
    for c in cells:
        outs = [flow[(c, nb)] for nb in _box_nbrs(c[0], c[1], n)]
        ins = [flow[(nb, c)] for nb in _box_nbrs(c[0], c[1], n)]
        M.Add(sum(outs) - sum(ins) == inject[c] - live[c])

    # ----- soft hint (warm start, optional) -----
    if initial_hint is not None:
        for c in cells:
            v = int(initial_hint[c[0]][c[1]])
            assert v in (0, 1), v
            M.AddHint(live[c], v)

    # ----- objective -----
    M.Maximize(total_live)

    # ----- solve -----
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = int(workers)
    solver.parameters.random_seed = int(seed)
    solver.parameters.log_search_progress = bool(log_search_progress)

    t0 = time.time()
    status = solver.Solve(M)
    elapsed = time.time() - t0

    # ----- decode -----
    grid = None
    vres = None
    cells_count = -1
    proven = False

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        grid = [[0] * n for _ in range(n)]
        for c in cells:
            if solver.Value(live[c]) == 1:
                grid[c[0]][c[1]] = 1
        cells_count = sum(sum(row) for row in grid)
        proven = status == cp_model.OPTIMAL
        vres = verify(grid, n, cells_count)

    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }.get(status, str(status))

    return {
        "n": n,
        "cells": cells_count,
        "proven_optimal": proven,
        "status": status_name,
        "elapsed_s": round(elapsed, 2),
        "verified": (vres[0] if vres else None),
        "verify_msg": (vres[1] if vres else "no model"),
        "grid": grid,
        "objective_value": solver.ObjectiveValue() if grid is not None else None,
        "best_objective_bound": solver.BestObjectiveBound() if grid is not None else None,
        "workers": workers,
        "seed": seed,
    }


def show_grid(grid):
    if not grid:
        return "(none)"
    return "\n".join("".join("#" if c else "." for c in row) for row in grid)


if __name__ == "__main__":
    import argparse, json

    p = argparse.ArgumentParser(description="CP-SAT connected-still-life solver.")
    p.add_argument("ns", nargs="*", type=int, default=[8])
    p.add_argument("-t", "--time-limit", type=float, default=120.0)
    p.add_argument("-j", "--workers", type=int, default=4)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--save-json", action="store_true",
                   help="Write connected_stilllife_n{N}_cpsat.json on success.")
    args = p.parse_args()

    for n in args.ns:
        print(f"\n=== CP-SAT n={n} | workers={args.workers} | time_limit={args.time_limit}s | seed={args.seed} ===",
              flush=True)
        r = solve_cpsat(n, time_limit=args.time_limit, workers=args.workers,
                        seed=args.seed, log_search_progress=args.verbose)
        tag = "PROVEN OPTIMAL" if r["proven_optimal"] else \
              ("best-found (not proven)" if r["cells"] >= 0 else "no model")
        vtag = "verified OK" if r["verified"] else f"VERIFY FAIL: {r['verify_msg']}"
        print(f"n={n:2d} | cells={r['cells']:4d} | {tag} | status={r['status']} | "
              f"{r['elapsed_s']}s | obj={r['objective_value']} bound={r['best_objective_bound']} | {vtag}")
        print(show_grid(r["grid"]))
        if args.save_json and r["verified"]:
            label = "PROVEN_OPT" if r["proven_optimal"] else "best"
            path = f"connected_stilllife_n{n}_cpsat_{label}_{r['cells']}.json"
            with open(path, "w") as f:
                json.dump({"n": r["n"], "claimed_cells": r["cells"], "grid": r["grid"]}, f)
            print(f"wrote {path}")
