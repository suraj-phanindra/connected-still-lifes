"""Independent triangulation of Phase 1 results: ask clingo whether ANY
connected still life with cell-count >= target exists in an n x n box.

Procedure:
  - Load the ASP-2013 encoding (with the same fixes as run_solve.py).
  - Strip the #maximize / weak-constraint objective.
  - Add an integrity constraint requiring sum(lives) >= target.
  - Solve. SAT => witness exists at >= target cells; UNSAT => provably
    no connected still life with that many cells.

Cross-check for Phase 1:
  - (n=10, target=54) and (n=11, target=64) target the published
    Chu-Stuckey unconstrained ceilings. If clingo returns UNSAT,
    the ceiling is provably NOT realised by a connected pattern, so
    connected-optimum(n) < ceiling. Combined with the verified
    connected witness (53, 63), this independently confirms the
    CP-SAT exhaustion claims.
"""
from __future__ import annotations

import os
import sys
import time

import clingo

from run_solve import load_encoding   # reuses the rewrite of #sum -> #count

HERE = os.path.dirname(os.path.abspath(__file__))


def check(n: int, target: int, time_limit: float = 600.0, threads: int = 4, seed: int = 1):
    enc = load_encoding()
    # Remove the appended #maximize from load_encoding (we want pure feasibility).
    enc_lines = [ln for ln in enc.splitlines()
                 if not ln.strip().startswith("#maximize")]
    enc_lines.append(
        f":- #count{{X,Y : lives(X,Y), value(X), value(Y)}} < {target}."
    )
    body = "\n".join(enc_lines)

    ctl = clingo.Control()
    ctl.configuration.solve.parallel_mode = str(threads)
    ctl.configuration.solver.seed = str(seed)
    ctl.add("base", [], body)
    ctl.add("base", [], f"size({n}).")
    ctl.ground([("base", [])])

    witness = {"cells": -1, "grid": None}

    def on_model(m):
        lv = [(s.arguments[0].number, s.arguments[1].number)
              for s in m.symbols(atoms=True)
              if s.name == "lives" and len(s.arguments) == 2]
        witness["cells"] = len(lv)
        grid = [[0] * n for _ in range(n)]
        for (x, y) in lv:
            grid[x - 1][y - 1] = 1
        witness["grid"] = grid

    t0 = time.time()
    with ctl.solve(on_model=on_model, async_=True) as h:
        finished = h.wait(time_limit)
        if not finished:
            h.cancel()
        res = h.get()
    elapsed = time.time() - t0

    proven = bool(finished and res.exhausted and not res.interrupted)
    if res.satisfiable:
        verdict = f"SAT (witness with {witness['cells']} cells found)"
    elif res.unsatisfiable and proven:
        verdict = "UNSAT (no connected still life with that many cells exists)"
    elif finished and not res.satisfiable and not res.unsatisfiable:
        verdict = "UNKNOWN (clingo neither SAT nor UNSAT)"
    else:
        verdict = f"TIMEOUT after {elapsed:.1f}s (no proof)"

    return {
        "n": n,
        "target": target,
        "verdict": verdict,
        "satisfiable": bool(res.satisfiable),
        "unsatisfiable": bool(res.unsatisfiable),
        "exhausted": bool(res.exhausted),
        "interrupted": bool(res.interrupted),
        "finished": finished,
        "elapsed_s": round(elapsed, 1),
        "witness": witness if res.satisfiable else None,
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--cases", nargs="+", default=["10:54", "11:64"],
                   help='Cases in "n:target" form (default: 10:54 11:64).')
    p.add_argument("-t", "--time-limit", type=float, default=600.0)
    p.add_argument("-j", "--threads", type=int, default=4)
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args()

    for c in args.cases:
        n_s, t_s = c.split(":")
        n, tgt = int(n_s), int(t_s)
        print(f"\n=== n={n}  target={tgt}  threads={args.threads}  time={args.time_limit}s ===", flush=True)
        r = check(n, tgt, time_limit=args.time_limit, threads=args.threads, seed=args.seed)
        print(f"verdict: {r['verdict']}  elapsed={r['elapsed_s']}s "
              f"(SAT={r['satisfiable']}, UNSAT={r['unsatisfiable']}, "
              f"exhausted={r['exhausted']}, finished={r['finished']})")
