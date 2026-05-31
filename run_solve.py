"""Reproduce the ASPCOMP-2013 'Connected Still Life' benchmark with clingo,
decode each optimum to a grid, and re-verify with our CAISc-faithful checker.

Encoding credit: ASPCOMP 2013 Official Problem Suite ('Connected Still Life').
We strip the encoding's weak-constraint objective and append a clean clingo
#maximize so optimization syntax is unambiguous across clingo versions
(semantics identical: maximize live-cell count).

Two encoding fixes applied at load time:
  (1) #sum {1 : lives(...), diff(DX,DY)} collapses under strict ASP-Core-2
      (all 8 contributions share tuple (1) and saturate at 1). We rewrite to
      #count {DX,DY : lives(...), diff(DX,DY)} so it counts distinct offsets.
  (2) clingo's SolveHandle.get() MUST be called inside the `with` block, or
      the handle frees mid-call and segfaults.
"""
import argparse, os, sys, time
import clingo
from verifier import verify

HERE = os.path.dirname(os.path.abspath(__file__))
ENC_PATH = os.path.join(HERE, "still_life-encoding.txt")


def load_encoding(enc_path=ENC_PATH):
    raw = open(enc_path).read()
    # Restore intended neighbor-COUNTING semantics. As written, the aggregate
    # element "1 : lives(...), diff(DX,DY)" has no distinguishing term, so under
    # strict ASP-Core-2 all 8 contributions share tuple (1) and the sum saturates
    # at 1. Adding (DX,DY) terms makes it count distinct live-neighbor offsets.
    raw = raw.replace("#sum { 1 : lives(X+DX,Y+DY), diff(DX,DY) }",
                      "#count { DX,DY : lives(X+DX,Y+DY), diff(DX,DY) }")
    kept = []
    for ln in raw.splitlines():
        s = ln.strip()
        if s.startswith(":~"):
            continue                      # drop weak-constraint objective
        if s.startswith("%#maximise") or s.startswith("#maximise") or s.startswith("#maximize"):
            continue                      # drop (commented) objective
        kept.append(ln)
    kept.append("#maximize { 1, X, Y : lives(X,Y), value(X), value(Y) }.")
    return "\n".join(kept)


def solve_n(n, time_limit=120, threads=4, seed=1, enc_path=ENC_PATH, verbose=False):
    enc = load_encoding(enc_path)
    ctl = clingo.Control()
    # M5 has 4 performance + 6 efficiency cores; oversubscribing efficiency
    # cores adds heat without speedup on this fanless laptop, so default to 4.
    ctl.configuration.solve.parallel_mode = str(threads)
    ctl.configuration.solver.seed = str(seed)
    ctl.add("base", [], enc)
    ctl.add("base", [], f"size({n}).")
    ctl.ground([("base", [])])

    best = {"cells": -1, "lives": None, "cost": None, "proven": False, "improvements": []}

    t0 = time.time()

    def on_model(m):
        lv = [(s.arguments[0].number, s.arguments[1].number)
              for s in m.symbols(atoms=True)
              if s.name == "lives" and len(s.arguments) == 2]
        best["lives"] = lv
        best["cells"] = len(lv)
        best["cost"] = list(m.cost)
        best["proven"] = m.optimality_proven
        best["improvements"].append((round(time.time() - t0, 1), len(lv), m.optimality_proven))
        if verbose:
            print(f"  [t+{time.time()-t0:6.1f}s] cells={len(lv):3d} proven={m.optimality_proven}", flush=True)

    with ctl.solve(on_model=on_model, async_=True) as h:
        finished = h.wait(time_limit)
        if not finished:
            h.cancel()
        res = h.get()            # MUST be inside the with-block (handle valid)
    elapsed = time.time() - t0
    # Optimality criterion: clingo's #maximize search is monotonic. If the
    # search exhausted the space and is satisfiable, then the best model is
    # the true optimum -- no better model exists. The per-model
    # `Model.optimality_proven` flag is NOT reliably set on the final
    # improving model in clingo 5.8 under async_=True; the SolveResult is.
    proven_opt = bool(
        finished
        and res.satisfiable
        and res.exhausted
        and not res.interrupted
    )

    grid = None
    vres = None
    if best["lives"] is not None:
        grid = [[0] * n for _ in range(n)]
        for (x, y) in best["lives"]:
            grid[x - 1][y - 1] = 1            # coords are 1..N
        vres = verify(grid, n, best["cells"])

    return {
        "n": n,
        "cells": best["cells"],
        "proven_optimal": proven_opt,
        "elapsed_s": round(elapsed, 1),
        "verified": (vres[0] if vres else None),
        "verify_msg": (vres[1] if vres else "no model found in time"),
        "grid": grid,
        "improvements": best["improvements"],
        "threads": threads,
        "seed": seed,
    }


def show_grid(grid):
    if not grid:
        return "(none)"
    return "\n".join("".join("#" if c else "." for c in row) for row in grid)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Solve connected still life via clingo.")
    parser.add_argument("ns", nargs="*", type=int, default=[8],
                        help="Box sizes to solve (default: 8).")
    parser.add_argument("-t", "--time-limit", type=float, default=120.0,
                        help="Per-n wall-clock time limit in seconds (default: 120).")
    parser.add_argument("-j", "--threads", type=int, default=4,
                        help="clingo parallel_mode threads (default: 4 = M5 perf cores).")
    parser.add_argument("--seed", type=int, default=1, help="clingo solver seed.")
    parser.add_argument("--verbose", action="store_true",
                        help="Print each improving model as it arrives.")
    args = parser.parse_args()

    for n in args.ns:
        print(f"\n=== n={n} | threads={args.threads} | time_limit={args.time_limit}s | seed={args.seed} ===", flush=True)
        r = solve_n(n, time_limit=args.time_limit, threads=args.threads,
                    seed=args.seed, verbose=args.verbose)
        tag = "PROVEN OPTIMAL" if r["proven_optimal"] else f"best-found (<= {args.time_limit}s, not proven)"
        vtag = "verified OK" if r["verified"] else f"VERIFY FAIL: {r['verify_msg']}"
        print(f"n={n:2d} | cells={r['cells']:4d} | {tag} | {r['elapsed_s']}s | {vtag}")
        if r["improvements"]:
            print(f"  improvements (t, cells, proven): {r['improvements']}")
        print(show_grid(r["grid"]))
        print()
