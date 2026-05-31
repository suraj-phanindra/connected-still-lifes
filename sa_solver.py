"""Simulated-annealing engine for connected still life (Phase 2: n >= 16).

Design choices:
  - Hot loop in NumPy: cheap per-iteration cost without C/Rust ceremony.
    Repair work is delegated to verifier.verify on each candidate (O(n^2)).
  - Validity-or-reject acceptance: proposals that violate stability,
    no-birth-incl-exterior-ring, or 8-connectivity are rejected outright.
    Life constraints are too tight for naive cell-flips; rejection rates
    will be high, which the Metropolis criterion + multi-restart absorbs.
  - Multi-restart driver: many short, resumable restarts (per CLAUDE.md
    thermal advice).
  - Seeds:
      "random_sparse": ~25% density random init.
      "block_lattice": disjoint 2x2 blocks on a 3-period grid (verified
          still life, disconnected -- the SA must bridge it).
      "tile_n8": tile our n=8 PROVEN_OPT_32 pattern into the (n // 8) by
          (n // 8) corners of an n x n grid (the bulk of cells), letting
          the SA find bridges in the gaps.

Output: same dict shape as solve_cpsat / solve_n, so the same JSON-saving
pipeline applies.
"""
from __future__ import annotations

import glob
import json
import math
import os
import time
from typing import Optional

import numpy as np

from verifier import verify

HERE = os.path.dirname(os.path.abspath(__file__))


def _verify_grid_np(grid: np.ndarray) -> tuple[bool, str]:
    n = grid.shape[0]
    return verify(grid.tolist(), n, int(grid.sum()))


def block_lattice(n: int) -> np.ndarray:
    """Disjoint 2x2 blocks on a period-3 grid -- guaranteed-valid stilllife
    but disconnected. SA must add bridges to make it connected."""
    g = np.zeros((n, n), dtype=np.int8)
    for i in range(0, n - 1, 3):
        for j in range(0, n - 1, 3):
            g[i:i + 2, j:j + 2] = 1
    return g


def random_sparse(n: int, rng: np.random.Generator, density: float = 0.25) -> np.ndarray:
    """Random init at given density. Almost certainly invalid; useful only
    when followed by a long burn-in that finds valid neighbours."""
    return (rng.uniform(size=(n, n)) < density).astype(np.int8)


def tile_seed(n: int, base_grid: list[list[int]]) -> Optional[np.ndarray]:
    """Tile a smaller proven-optimal grid into the corners of an n x n grid.
    Each tile is offset to leave room for bridge cells in the gaps."""
    b = np.asarray(base_grid, dtype=np.int8)
    bn = b.shape[0]
    if n < bn:
        return None
    tiles = n // (bn + 1)  # leave a gap between tiles for bridges
    if tiles < 2:
        return None
    g = np.zeros((n, n), dtype=np.int8)
    for ti in range(tiles):
        for tj in range(tiles):
            r0 = ti * (bn + 1)
            c0 = tj * (bn + 1)
            if r0 + bn <= n and c0 + bn <= n:
                g[r0:r0 + bn, c0:c0 + bn] = b
    return g


def embed_largest_fit(n: int) -> Optional[np.ndarray]:
    """Embed the largest verified pattern that fits in n x n at (0,0).

    Looks for any connected_stilllife_n{m}_*.json with m <= n in the project
    directory, re-verifies, then picks the one with the most cells. Returns
    None if nothing fits or no JSONs exist.

    The embedded pattern remains a valid connected still life in the larger
    box because:
      - in-box stability is unchanged (same neighborhood arithmetic),
      - the previous exterior-ring no-birth check at row/col `m` is still
        satisfied (the dead cells just past the original box still have
        the same neighbor counts),
      - the new exterior ring at row/col n is far from the live region.
    """
    candidates = []
    for path in glob.glob(os.path.join(HERE, "connected_stilllife_n*.json")):
        try:
            d = json.load(open(path))
            bn = int(d["n"])
            if bn > n:
                continue
            claimed = int(d["claimed_cells"])
            grid = d["grid"]
            ok, _ = verify(grid, bn, claimed)
            if not ok:
                continue
            candidates.append((claimed, bn, grid, path))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    cells, bn, base, _ = candidates[0]
    g = np.zeros((n, n), dtype=np.int8)
    g[:bn, :bn] = np.asarray(base, dtype=np.int8)
    # Sanity-check the embedded grid is still valid in the larger box.
    ok, _ = verify(g.tolist(), n, int(g.sum()))
    if not ok:
        return None
    return g


def _propose_toggle_single(g: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Flip a single random cell."""
    out = g.copy()
    i, j = int(rng.integers(0, g.shape[0])), int(rng.integers(0, g.shape[1]))
    out[i, j] ^= 1
    return out


def _propose_rect_randomize(g: np.ndarray, rng: np.random.Generator, k: int = 3) -> np.ndarray:
    """Randomize a kxk subrectangle in place."""
    n = g.shape[0]
    out = g.copy()
    i = int(rng.integers(0, n - k + 1))
    j = int(rng.integers(0, n - k + 1))
    out[i:i + k, j:j + k] = (rng.uniform(size=(k, k)) < 0.5).astype(np.int8)
    return out


def sa_run(
    n: int,
    initial: np.ndarray,
    *,
    rng: np.random.Generator,
    iters: int = 50_000,
    T0: float = 4.0,
    T_min: float = 1e-3,
    rect_p: float = 0.3,
    rect_k: int = 3,
    log_every: int = 5_000,
    verbose: bool = False,
):
    """One SA restart from a given initial grid."""
    g = initial.copy().astype(np.int8)
    g_cells = int(g.sum())
    g_valid, _ = _verify_grid_np(g)

    best = g.copy()
    best_cells = g_cells if g_valid else -1
    cooling = (T_min / T0) ** (1.0 / max(iters, 1))
    T = T0

    n_acc = 0
    n_prop = 0
    n_valid_prop = 0
    t0 = time.time()

    for it in range(iters):
        if rng.uniform() < rect_p:
            cand = _propose_rect_randomize(g, rng, rect_k)
        else:
            cand = _propose_toggle_single(g, rng)
        n_prop += 1
        c_cells = int(cand.sum())
        if c_cells == g_cells and g_valid and np.array_equal(cand, g):
            # no-op proposal
            T *= cooling
            continue

        ok, _ = _verify_grid_np(cand)
        if not ok:
            T *= cooling
            continue
        n_valid_prop += 1

        dE = c_cells - g_cells if g_valid else c_cells  # if g was invalid, any valid grid is better
        accept = (dE >= 0) or (rng.uniform() < math.exp(dE / max(T, 1e-9)))
        if accept:
            g = cand
            g_cells = c_cells
            g_valid = True
            n_acc += 1
            if g_cells > best_cells:
                best = g.copy()
                best_cells = g_cells
                if verbose:
                    print(f"  [iter {it:>7} t+{time.time()-t0:6.1f}s T={T:.3f}] new best={best_cells}", flush=True)

        T *= cooling

        if verbose and log_every and it and it % log_every == 0:
            print(f"  [iter {it:>7} t+{time.time()-t0:6.1f}s T={T:.3f}] best={best_cells} valid_prop={n_valid_prop}/{n_prop} acc={n_acc}", flush=True)

    return {
        "best_cells": best_cells,
        "best_grid": best.tolist() if best_cells >= 0 else None,
        "iters": iters,
        "n_prop": n_prop,
        "n_valid_prop": n_valid_prop,
        "n_acc": n_acc,
        "elapsed_s": round(time.time() - t0, 2),
        "T_end": T,
    }


def multi_restart(
    n: int,
    *,
    seeds: tuple[str, ...] = ("embed_largest", "embed_largest", "embed_largest"),
    restarts: int = 6,
    iters_per: int = 50_000,
    base_rng_seed: int = 1,
    verbose: bool = False,
    save_json: bool = False,
):
    rng = np.random.default_rng(base_rng_seed)

    # Load the n=8 PROVEN_OPT pattern (if present) for tile_n8 seed.
    n8_path = os.path.join(HERE, "connected_stilllife_n8_PROVEN_OPT_32.json")
    n8_grid = None
    if os.path.exists(n8_path):
        n8_grid = json.load(open(n8_path))["grid"]

    overall_best = {"cells": -1, "grid": None, "seed": None, "restart": None}
    summaries = []
    for r in range(restarts):
        seed_name = seeds[r % len(seeds)]
        init = None
        if seed_name == "embed_largest":
            init = embed_largest_fit(n)
            if init is None:
                seed_name = "block_lattice_fallback"
                init = block_lattice(n)
        elif seed_name == "block_lattice":
            init = block_lattice(n)
        elif seed_name == "random_sparse":
            init = random_sparse(n, rng, density=0.30)
        elif seed_name == "tile_n8":
            tiled = tile_seed(n, n8_grid) if n8_grid is not None else None
            init = tiled if tiled is not None else block_lattice(n)
            seed_name = "tile_n8" if tiled is not None else "block_lattice_fallback"
        else:
            raise ValueError(seed_name)

        # Confirm the seed is itself a valid still life; if not, SA starts
        # with best_cells = -1 and only saves valid grids it finds along the way.
        seed_ok, _ = verify(init.tolist(), n, int(init.sum()))
        if verbose:
            print(f"\n--- restart {r+1}/{restarts}  seed={seed_name}  init_cells={int(init.sum())}  init_valid={seed_ok} ---")

        res = sa_run(n, init, rng=rng, iters=iters_per, verbose=verbose)
        res["seed_name"] = seed_name
        res["restart_idx"] = r
        res["init_valid"] = seed_ok
        summaries.append(res)

        if res["best_cells"] > overall_best["cells"]:
            overall_best = {"cells": res["best_cells"], "grid": res["best_grid"],
                            "seed": seed_name, "restart": r, "iters": iters_per}
            if verbose:
                print(f"  ** new overall best: {overall_best['cells']} cells **")

    # Final verifier round-trip.
    verified = False
    msg = "no valid grid found"
    if overall_best["grid"] is not None:
        ok, msg = verify(overall_best["grid"], n, overall_best["cells"])
        verified = ok

    if save_json and verified:
        path = os.path.join(HERE, f"connected_stilllife_n{n}_sa_best_{overall_best['cells']}.json")
        with open(path, "w") as f:
            json.dump({"n": n, "claimed_cells": overall_best["cells"], "grid": overall_best["grid"]}, f)

    return {
        "n": n,
        "best_cells": overall_best["cells"],
        "best_grid": overall_best["grid"],
        "best_seed_name": overall_best["seed"],
        "best_restart_idx": overall_best["restart"],
        "verified": verified,
        "verify_msg": msg,
        "restarts": restarts,
        "iters_per": iters_per,
        "summaries": summaries,
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="SA driver for connected still life.")
    p.add_argument("ns", nargs="*", type=int, default=[16])
    p.add_argument("--restarts", type=int, default=6)
    p.add_argument("--iters", type=int, default=50_000, help="iterations per restart")
    p.add_argument("--seed", type=int, default=1, help="base RNG seed")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--save-json", action="store_true")
    args = p.parse_args()

    for n in args.ns:
        print(f"\n=== SA n={n}  restarts={args.restarts}  iters={args.iters}  seed={args.seed} ===")
        r = multi_restart(
            n,
            restarts=args.restarts,
            iters_per=args.iters,
            base_rng_seed=args.seed,
            verbose=args.verbose,
            save_json=args.save_json,
        )
        tag = "verified OK" if r["verified"] else f"VERIFY: {r['verify_msg']}"
        print(f"n={n:2d} | best_cells={r['best_cells']:4d} | seed={r['best_seed_name']} | restart={r['best_restart_idx']} | {tag}")
        if r["best_grid"] is not None:
            for row in r["best_grid"]:
                print("".join("#" if c else "." for c in row))
