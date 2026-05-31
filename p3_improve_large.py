"""P3 driver: improve n=16-21 best-found with longer CP-SAT-as-heuristic.

Per the user's plan: ~1-2 h each, block-lattice hint (or warm-start from
the existing best, whichever is denser). Save any improved verifier-valid
pattern under a NEW filename; never overwrite. Honest best-found labels.

Sequence solver runs per n, never concurrent (fanless M5 throttle).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time

import numpy as np

from cpsat_solver import solve_cpsat
from sa_solver import block_lattice
from verifier import verify

HERE = os.path.dirname(os.path.abspath(__file__))


def load_best_hint(n: int) -> tuple[np.ndarray | None, int, str]:
    """Return (grid, cells, source) for the highest-cell-count verifier-valid
    grid already saved for this n. None if nothing applicable."""
    best = (None, -1, "")
    for p in glob.glob(os.path.join(HERE, f"connected_stilllife_n{n}_*.json")):
        try:
            d = json.load(open(p))
            if d.get("n") != n:
                continue
            ok, _ = verify(d["grid"], d["n"], d["claimed_cells"])
            if not ok:
                continue
            if d["claimed_cells"] > best[1]:
                best = (np.asarray(d["grid"], dtype=int), int(d["claimed_cells"]),
                        os.path.basename(p))
        except Exception:
            continue
    return best


def run_one(n: int, hours: float, seed: int = 1):
    print(f"\n=== P3 n={n}  hours={hours} ===", flush=True)
    budget_s = hours * 3600.0

    warm_grid, warm_cells, warm_src = load_best_hint(n)
    bl = block_lattice(n)
    bl_cells = int(bl.sum())

    # Pick the denser hint (warm-start if its cell count beats block_lattice).
    if warm_grid is not None and warm_cells >= bl_cells:
        hint = warm_grid
        hint_label = f"warm-start ({warm_cells} cells from {warm_src})"
    else:
        hint = bl
        hint_label = f"block_lattice ({bl_cells} cells)"
    print(f"hint = {hint_label}", flush=True)

    t0 = time.time()
    r = solve_cpsat(
        n,
        time_limit=budget_s,
        workers=4,
        seed=seed,
        initial_hint=hint.tolist(),
        log_search_progress=False,
    )
    wall = time.time() - t0
    print(f"result: cells={r['cells']} status={r['status']} obj={r['objective_value']} "
          f"bound={r['best_objective_bound']} wall={wall:.1f}s verified={r['verified']}",
          flush=True)

    # Save if VALID AND strictly improves the existing best.
    if r["verified"] and r["grid"] is not None and r["cells"] > warm_cells:
        label = "PROVEN_OPT" if r["proven_optimal"] else "BEST_FOUND"
        path = os.path.join(
            HERE, f"connected_stilllife_n{n}_p3_cpsat_{label}_{r['cells']}.json"
        )
        with open(path, "w") as f:
            json.dump({"n": r["n"], "claimed_cells": r["cells"], "grid": r["grid"]}, f)
        print(f"  ** improved over {warm_cells} -> {r['cells']}, wrote {path}", flush=True)
    elif r["verified"]:
        print(f"  no improvement over {warm_cells} (got {r['cells']})", flush=True)
    return r


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--ns", type=int, nargs="+", default=[16, 17, 19, 20, 21])
    p.add_argument("--hours", type=float, default=1.5)
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args()

    summary = []
    for n in args.ns:
        r = run_one(n, hours=args.hours, seed=args.seed)
        summary.append((n, r["cells"], r["status"]))

    print("\n=== P3 sweep summary ===")
    for n, cells, st in summary:
        print(f"  n={n:3d}  cells={cells:5d}  status={st}")
