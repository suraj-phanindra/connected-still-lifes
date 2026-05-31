"""P2 driver: try to close the n=13 [87, 89] gap.

Multi-strategy, sequenced (NEVER concurrent — fanless M5):
  1. SCF + block_lattice hint, 1.5 h.
  2. Spanning-tree + block_lattice hint, 1.5 h.
  3. (If neither closed): SCF + warm-start from BEST_FOUND_87 hint, 30 min.

After each strategy, save best verifier-valid grid under a NEW filename
(do NOT overwrite existing JSONs). Log per-strategy result. Stop early if
any strategy returns OPTIMAL (status proven).
"""
from __future__ import annotations

import json
import os
import time

from cpsat_solver import solve_cpsat
from cpsat_solver_st import solve_cpsat_st
from sa_solver import block_lattice
from verifier import verify

HERE = os.path.dirname(os.path.abspath(__file__))


def _try(label: str, solver_fn, n, budget_s, hint, seed=1):
    print(f"\n--- {label} | budget={budget_s}s | hint_cells={int(hint.sum()) if hint is not None else 'none'} ---",
          flush=True)
    t0 = time.time()
    hint_arg = hint.tolist() if hint is not None else None
    r = solver_fn(n, time_limit=budget_s, workers=4, seed=seed, initial_hint=hint_arg)
    wall = time.time() - t0
    print(f"   cells={r['cells']}  status={r['status']}  obj={r['objective_value']}  "
          f"bound={r['best_objective_bound']}  wall={wall:.1f}s  verified={r['verified']}",
          flush=True)
    if r["verified"] and r["grid"] is not None:
        label_tag = "PROVEN_OPT" if r["proven_optimal"] else "BEST_FOUND"
        path = os.path.join(
            HERE, f"connected_stilllife_n{n}_p2_{label}_{label_tag}_{r['cells']}.json"
        )
        with open(path, "w") as f:
            json.dump({"n": r["n"], "claimed_cells": r["cells"], "grid": r["grid"]}, f)
        print(f"   wrote {path}", flush=True)
    return r


def close_n(n: int, total_budget_h: float = 3.0, seed: int = 1):
    # 1/3 of budget for SCF+hint, 1/3 for ST+hint, 1/3 reserved.
    per_strat = total_budget_h * 3600 / 3.0

    hint = block_lattice(n)

    # 1) SCF + block_lattice hint
    r_scf = _try("SCF + block_lattice", solve_cpsat, n, per_strat, hint, seed=seed)
    if r_scf["proven_optimal"]:
        return {"closed": True, "winner": "SCF+block_lattice", "result": r_scf}

    # 2) Spanning-tree + block_lattice hint
    r_st = _try("ST + block_lattice", solve_cpsat_st, n, per_strat, hint, seed=seed)
    if r_st["proven_optimal"]:
        return {"closed": True, "winner": "ST+block_lattice", "result": r_st}

    # 3) SCF + warm-start from highest-cell-count verified n=N json on disk.
    import glob, numpy as np
    best_grid = None
    best_cells = -1
    for p in glob.glob(os.path.join(HERE, f"connected_stilllife_n{n}_*.json")):
        try:
            d = json.load(open(p))
            if d["n"] != n:
                continue
            ok, _ = verify(d["grid"], d["n"], d["claimed_cells"])
            if not ok:
                continue
            if d["claimed_cells"] > best_cells:
                best_cells = d["claimed_cells"]
                best_grid = np.asarray(d["grid"], dtype=int)
                best_src = os.path.basename(p)
        except Exception:
            continue
    warm = best_grid
    if warm is not None:
        print(f"\n[strategy 3] warm-start hint = {best_cells} cells from {best_src}", flush=True)
    if warm is not None:
        r3 = _try("SCF + warm-start", solve_cpsat, n, per_strat, warm, seed=seed)
        if r3["proven_optimal"]:
            return {"closed": True, "winner": "SCF+warm-start", "result": r3}
        return {"closed": False, "best": max([r_scf, r_st, r3], key=lambda r: r['cells'])}
    return {"closed": False, "best": max([r_scf, r_st], key=lambda r: r['cells'])}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=13)
    p.add_argument("--hours", type=float, default=3.0)
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args()
    out = close_n(args.n, total_budget_h=args.hours, seed=args.seed)
    print("\n=== summary ===")
    print(json.dumps({k: v for k, v in out.items() if k != "result" and k != "best"}, indent=2))
    final = out.get("result") or out.get("best")
    if final:
        print(f"final: cells={final['cells']}  proven={final['proven_optimal']}  status={final['status']}  bound={final['best_objective_bound']}")
