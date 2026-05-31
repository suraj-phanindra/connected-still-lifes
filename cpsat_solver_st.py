"""CP-SAT exact engine for connected still life — SECOND connectivity
encoding (spanning-tree / parent-pointer with depth) for independent
triangulation of the SCF-encoded results in cpsat_solver.py.

Stability + interior no-birth + exterior-ring no-birth: identical to
cpsat_solver.py (line-by-line). Connectivity is the *only* difference.

Spanning-tree connectivity:
  - For each ordered pair (c, c') with c' in c's Moore-8 in-box neighborhood,
    Boolean `parent_dir[(c, c')]` means "c' is the parent of c in the
    spanning tree".
  - For each cell c: live(c) ⇔ root(c) + Σ parent_dir[(c, c')] == 1
    (live cell has either root status or exactly one parent neighbor).
  - parent_dir[(c, c')] ⇒ live(c) ∧ live(c').
  - Σ_c root(c) ≤ 1; combined with conservation, this forces exactly one
    root when any cell is live.
  - depth(c) ∈ [0, n² - 1]; root cell has depth 0; for each parent edge,
    depth(c) = depth(c') + 1. Depth monotonicity forbids cycles.

This is a structurally different formulation from SCF: no arc flows,
no super-source, no inject linearization. If both encodings return the
same OPTIMAL value on the same instance, the chance both have the same
connectivity bug is small.
"""
from __future__ import annotations

import time
from typing import Iterator

from ortools.sat.python import cp_model

from verifier import verify

N8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _in_box(i: int, j: int, n: int) -> bool:
    return 0 <= i < n and 0 <= j < n


def _box_nbrs(i: int, j: int, n: int) -> Iterator[tuple[int, int]]:
    for di, dj in N8:
        ii, jj = i + di, j + dj
        if _in_box(ii, jj, n):
            yield (ii, jj)


def solve_cpsat_st(
    n: int,
    time_limit: float = 120.0,
    workers: int = 4,
    seed: int = 1,
    log_search_progress: bool = False,
    initial_hint: "list[list[int]] | None" = None,
):
    """Spanning-tree CP-SAT solver. Same return shape as solve_cpsat."""
    M = cp_model.CpModel()
    big_M = n * n
    cells = [(i, j) for i in range(n) for j in range(n)]

    # ----- decision variables -----
    live = {c: M.NewBoolVar(f"live_{c[0]}_{c[1]}") for c in cells}
    root = {c: M.NewBoolVar(f"root_{c[0]}_{c[1]}") for c in cells}
    total_live = M.NewIntVar(0, big_M, "total_live")
    M.Add(total_live == sum(live[c] for c in cells))

    # parent_dir[(c, c')]: c' is the parent of c (live c' chosen as parent).
    parent_dir = {}
    for c in cells:
        for nb in _box_nbrs(c[0], c[1], n):
            parent_dir[(c, nb)] = M.NewBoolVar(f"par_{c[0]}_{c[1]}__{nb[0]}_{nb[1]}")

    # depth[c]: BFS-level / spanning-tree distance from the root.
    depth = {c: M.NewIntVar(0, big_M - 1, f"depth_{c[0]}_{c[1]}") for c in cells}

    # ----- stability + interior no-birth (identical to cpsat_solver.py) -----
    for c in cells:
        nbr_sum = sum(live[nb] for nb in _box_nbrs(c[0], c[1], n))
        M.Add(nbr_sum >= 2).OnlyEnforceIf(live[c])
        M.Add(nbr_sum <= 3).OnlyEnforceIf(live[c])
        M.Add(nbr_sum != 3).OnlyEnforceIf(live[c].Not())

    # ----- exterior-ring no-birth (identical) -----
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

    # ----- root choice (same shape as solve_cpsat) -----
    M.Add(sum(root[c] for c in cells) <= 1)
    for c in cells:
        M.AddImplication(root[c], live[c])
    has_live = M.NewBoolVar("has_live")
    M.Add(total_live >= 1).OnlyEnforceIf(has_live)
    M.Add(total_live == 0).OnlyEnforceIf(has_live.Not())
    M.Add(sum(root[c] for c in cells) == 1).OnlyEnforceIf(has_live)
    M.Add(sum(root[c] for c in cells) == 0).OnlyEnforceIf(has_live.Not())

    # ----- spanning-tree connectivity -----
    # 1) Each live cell has exactly one of: root status OR one parent direction.
    #    Dead cells have all parent_dir == 0 and root == 0.
    for c in cells:
        in_nbrs_par = [parent_dir[(c, nb)] for nb in _box_nbrs(c[0], c[1], n)]
        M.Add(sum(in_nbrs_par) + root[c] == live[c])

    # 2) parent_dir[(c, c')] implies both endpoints are live.
    for (c, nb), pid in parent_dir.items():
        M.AddImplication(pid, live[c])
        M.AddImplication(pid, live[nb])

    # 3) Root has depth 0.
    for c in cells:
        M.Add(depth[c] == 0).OnlyEnforceIf(root[c])

    # 4) For each parent edge: depth(c) = depth(parent) + 1. Forbids cycles.
    for (c, nb), pid in parent_dir.items():
        M.Add(depth[c] == depth[nb] + 1).OnlyEnforceIf(pid)

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

    p = argparse.ArgumentParser(description="Spanning-tree CP-SAT solver (triangulation).")
    p.add_argument("ns", nargs="*", type=int, default=[10])
    p.add_argument("-t", "--time-limit", type=float, default=600.0)
    p.add_argument("-j", "--workers", type=int, default=4)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--save-json", action="store_true")
    args = p.parse_args()

    for n in args.ns:
        print(f"\n=== CP-SAT-ST n={n} | workers={args.workers} | time_limit={args.time_limit}s | seed={args.seed} ===",
              flush=True)
        r = solve_cpsat_st(n, time_limit=args.time_limit, workers=args.workers, seed=args.seed)
        tag = "PROVEN OPTIMAL" if r["proven_optimal"] else \
              ("best-found (not proven)" if r["cells"] >= 0 else "no model")
        vtag = "verified OK" if r["verified"] else f"VERIFY FAIL: {r['verify_msg']}"
        print(f"n={n:2d} | cells={r['cells']:4d} | {tag} | status={r['status']} | "
              f"{r['elapsed_s']}s | obj={r['objective_value']} bound={r['best_objective_bound']} | {vtag}")
        print(show_grid(r["grid"]))
        if args.save_json and r["verified"]:
            label = "PROVEN_OPT" if r["proven_optimal"] else "best"
            path = f"connected_stilllife_n{n}_cpsat_ST_{label}_{r['cells']}.json"
            with open(path, "w") as f:
                json.dump({"n": r["n"], "claimed_cells": r["cells"], "grid": r["grid"]}, f)
            print(f"wrote {path}")
