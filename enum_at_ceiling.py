"""P1(b) triangulation: clingo enumerates EVERY stability-only still life
of cardinality EXACTLY `target` (no connectivity constraint), and we check
each one for 8-connectivity with verifier.py.

If clingo's enumeration EXHAUSTS and every enumerated witness is
disconnected, then no connected still life with `target` cells exists
in an n x n box — fully independent of the CP-SAT model. Combined with
our verified `target - 1`-cell connected witness, this triangulates
connected-optimum(n) = target - 1.

Encoding mods (vs. still_life-encoding.txt):
  - Strip the connectedness `reached/2` rules and integrity constraint.
  - Strip the weak-constraint objective.
  - Add `:- #count{X,Y : lives(X,Y), value(X), value(Y)} != target.`
  - Apply the same `#sum -> #count` rewrite as run_solve.py (aggregate
    tuple-collapse fix).
"""
from __future__ import annotations

import argparse
import os
import time

import clingo

from run_solve import load_encoding
from verifier import verify

HERE = os.path.dirname(os.path.abspath(__file__))


def build_stability_only_encoding(target: int) -> str:
    """Return a clingo program identical to load_encoding() except that
    the connectivity section is removed and a hard equality on the cell
    count is added."""
    raw = load_encoding()  # already has #sum -> #count rewrite + #maximize stripped
    lines = raw.splitlines()
    out = []
    skip_block = False
    for ln in lines:
        s = ln.strip()
        # Connectivity comment marker
        if s.startswith("% connectedness"):
            skip_block = True
            continue
        # Stop skipping when we hit the next section (objective comment or maximize)
        if skip_block:
            if s.startswith("% maximise") or s.startswith("%#maximise") or s == "" or s.startswith("#maximize"):
                skip_block = False
                # do not output the blank/comment marker either; just fall through
            else:
                # Lines inside connectivity block: skip
                continue
        # Drop the appended #maximize (we're not optimizing).
        if s.startswith("#maximize") or s.startswith("#maximise") or s.startswith("%#maximise") or s.startswith(":~"):
            continue
        out.append(ln)
    # Two-sided count equality: `count > target` and `count < target` are
    # each forbidden, so the model count must be exactly `target`.
    out.append(
        f":- #count{{X,Y : lives(X,Y), value(X), value(Y)}} > {target}."
    )
    out.append(
        f":- #count{{X,Y : lives(X,Y), value(X), value(Y)}} < {target}."
    )
    return "\n".join(out)


def enumerate(n: int, target: int, *,
              time_limit: float = 1800.0,
              threads: int = 4,
              seed: int = 1,
              max_models: int = 0,
              verbose: bool = True):
    body = build_stability_only_encoding(target)
    ctl = clingo.Control([f"--models={max_models}"])
    ctl.configuration.solve.parallel_mode = str(threads)
    ctl.configuration.solver.seed = str(seed)
    ctl.add("base", [], body)
    ctl.add("base", [], f"size({n}).")
    ctl.ground([("base", [])])

    counts = {"total": 0, "connected": 0, "disconnected": 0, "invalid": 0}
    first_connected = None
    t0 = time.time()

    def on_model(m):
        counts["total"] += 1
        lv = [(s.arguments[0].number, s.arguments[1].number)
              for s in m.symbols(atoms=True)
              if s.name == "lives" and len(s.arguments) == 2]
        grid = [[0] * n for _ in range(n)]
        for (x, y) in lv:
            grid[x - 1][y - 1] = 1
        # Use verifier.verify, which checks ALL of: stability, no-birth
        # incl. exterior ring, AND 8-connectivity. If verifier says it's
        # valid, that's a connected still life at the target cardinality.
        ok, msg = verify(grid, n, len(lv))
        if ok:
            counts["connected"] += 1
            if first_connected is None:
                # cache the first one for sanity
                first_connected_grid = [row[:] for row in grid]
                # (closure trick: bind via list mutation)
                first_connected_holder[0] = first_connected_grid
        elif "disconnected" in msg:
            counts["disconnected"] += 1
        else:
            # Should never happen: the encoding enforces stability+no-birth,
            # so any model should pass verify EXCEPT for the connectivity check.
            counts["invalid"] += 1
        if verbose and counts["total"] % 10000 == 0:
            elapsed = time.time() - t0
            print(f"  [t+{elapsed:6.1f}s] models={counts['total']:>7}  "
                  f"connected={counts['connected']} disconnected={counts['disconnected']} "
                  f"invalid={counts['invalid']}", flush=True)

    first_connected_holder = [None]

    with ctl.solve(on_model=on_model, async_=True) as h:
        finished = h.wait(time_limit)
        if not finished:
            h.cancel()
        res = h.get()
    elapsed = time.time() - t0

    # Exhausted = clingo finished enumeration (no more models exist).
    exhausted = bool(finished and res.exhausted and not res.interrupted)

    return {
        "n": n,
        "target": target,
        "elapsed_s": round(elapsed, 1),
        "finished": finished,
        "exhausted": exhausted,
        "satisfiable": bool(res.satisfiable),
        "unsatisfiable": bool(res.unsatisfiable),
        "counts": counts,
        "first_connected_grid": first_connected_holder[0],
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cases", nargs="+", default=["10:54"])
    p.add_argument("-t", "--time-limit", type=float, default=1800.0)
    p.add_argument("-j", "--threads", type=int, default=4)
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args()

    for case in args.cases:
        n_s, t_s = case.split(":")
        n, tgt = int(n_s), int(t_s)
        print(f"\n=== enumerate n={n} target={tgt}  threads={args.threads}  budget={args.time_limit}s ===",
              flush=True)
        r = enumerate(n, tgt, time_limit=args.time_limit, threads=args.threads, seed=args.seed)
        print(f"  elapsed={r['elapsed_s']}s  finished={r['finished']}  exhausted={r['exhausted']}  "
              f"sat={r['satisfiable']}  unsat={r['unsatisfiable']}")
        c = r["counts"]
        print(f"  total models enumerated: {c['total']}")
        print(f"    connected (= still life + 8-connected at target): {c['connected']}")
        print(f"    disconnected: {c['disconnected']}")
        print(f"    unexpected verify failure (encoding bug?):       {c['invalid']}")
        # Verdict
        if r["unsatisfiable"]:
            verdict = ("UNSAT under stability-only at this target — "
                       "no stable pattern of this cardinality exists at all")
        elif r["exhausted"] and c["connected"] == 0:
            verdict = (f"PROVEN connected-optimum({n}) < {tgt}: "
                       f"every one of {c['total']} stability-only models at {tgt} "
                       f"cells is disconnected, and search EXHAUSTED")
        elif c["connected"] >= 1:
            verdict = (f"FOUND a connected stability-only model with {tgt} cells "
                       f"— rules out the optimum-below-ceiling claim!")
        else:
            verdict = ("INCONCLUSIVE: search did not exhaust within the budget; "
                       "best we can say is no connected witness with this cell count "
                       "was found among the enumerated models")
        print(f"  VERDICT: {verdict}", flush=True)
