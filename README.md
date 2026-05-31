# Connected Still Lifes

Solving the **Connected Maximum-Density Still Life** problem in Conway's Game of Life
with a deterministic verifier and a hybrid CP-SAT + ASP solver stack. Verified
per-n results for n ∈ {8, 9, 10, 11, 13, 15, 16, 17, 19, 20, 21, 31, 32}.

This repository accompanies the paper *Connected Maximum-Density Still Lifes:
An Agentic Verifier + Proposer Loop* (CAISc 2026, Verifiable Track). PDF:
[`connected_still_life_CAISc2026.pdf`](connected_still_life_CAISc2026.pdf).

## Headline results

| n  | best verified | proven? | density | Chu–Stuckey ceiling | gap |
|---:|--------------:|:-------:|--------:|--------------------:|----:|
|  8 | **32** | yes (clingo exhaust + CP-SAT SCF + CP-SAT ST) | 50.00 % |  36 |  4 |
|  9 | **43** | yes (ceiling-matching + CP-SAT SCF) | 53.09 % |  43 |  0 |
| 10 | **53** | yes (CP-SAT SCF + CP-SAT ST both `OPTIMAL`) | 53.00 % |  54 |  1 |
| 11 | **63** | yes (CP-SAT SCF + CP-SAT ST both `OPTIMAL`) | 52.07 % |  64 |  1 |
| 13 | 88 | no (CP-SAT bound 89 ⇒ optimum ∈ {88, 89}) | 52.07 % |  90 | ≥ 1 |
| 15 | 116 | no (Chu–Stuckey ⇒ optimum ∈ [116, 119]) | 51.56 % | 119 | ≥ 3 |
| 16 | 131 | no (CP-SAT-as-heuristic, block-lattice hint) | 51.17 % | 136 | ≥ 5 |
| 17 | 147 | no (same; P3 improvement over 138) | 50.87 % | 152 | ≥ 5 |
| 19 | 179 | no (same) | 49.58 % | 190 | ≥ 11 |
| 20 | 201 | no (same; P3 improvement over 195) | 50.25 % | 210 | ≥ 9 |
| 21 | 221 | no (same) | 50.11 % | 232 | ≥ 11 |
| 31 | 116 | placeholder (embed-only baseline) | 12.07 % | 497 | ≥ 381 |
| 32 | 116 | placeholder (embed-only baseline) | 11.33 % | 531 | ≥ 415 |

For n ∈ {8, 9, 10, 11} the connected optimum is proven. For n ∈ {13, 15} we
give best-found witnesses and bounds. For n ∈ {16…21} we give best-found
witnesses from CP-SAT used as a budgeted heuristic. For n ∈ {31, 32} the
artifacts are explicit placeholders; closing those gaps is future work.

## What's in the box

```
verifier.py                <- official-grader-faithful verifier (single source of truth)
cpsat_solver.py            <- CP-SAT exact engine, single-commodity-flow connectivity
cpsat_solver_st.py         <- CP-SAT exact engine, spanning-tree connectivity (independent)
run_solve.py               <- ASP / clingo solver (ASP-2013 encoding + the two fixes)
feasibility.py             <- ASP ceiling-feasibility cross-check
enum_at_ceiling.py         <- ASP stability-only ceiling enumeration
sa_solver.py               <- simulated-annealing proposer (documents the naive-SA failure)
p2_close_n13.py            <- multi-strategy n=13 closing driver
p3_improve_large.py        <- n=16-21 best-found improvement driver
print_table.py             <- walks the JSONs, re-verifies, prints the per-n table
still_life-encoding.txt    <- third-party ASP-2013 connected-still-life encoding
still_life-sample/         <- ASP-2013 sample size facts (size(N) per instance)
connected_stilllife_n*_*.json   <- every verifier-valid pattern we produced, all box sizes
LOG.md                     <- run-by-run experiment record (seeds, budgets, wall-clock)
connected_still_life_CAISc2026.pdf  <- the paper
connected_still_life_CAISc2026.tex  <- paper source (uses caisc_2026.sty)
caisc_2026.sty             <- conference style file
```

JSON naming convention: `connected_stilllife_n{N}_{LABEL}_{CELLS}.json`, where
`LABEL` is `PROVEN_OPT` (proven-optimal), `BEST_FOUND` (verifier-valid but not
proven optimal), or `embed_only` (placeholder lower bound). The submission
format is `{ "n", "claimed_cells", "grid" }`.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install ortools clingo numpy

# 1) Verifier golden tests
python3 verifier.py

# 2) Re-verify every artifact in the repo
python3 print_table.py

# 3) Reproduce a proven-optimal result (two independent connectivity encodings)
python3 cpsat_solver.py    8 9 10 11 -t 600
python3 cpsat_solver_st.py 8 10 11   -t 600

# 4) Reproduce the ASP cross-checks
python3 run_solve.py 8 9
python3 enum_at_ceiling.py --cases 8:36 10:54 11:64

# 5) Phase 2 / Phase 3 heuristic runs (long)
python3 p2_close_n13.py --n 13 --hours 3
python3 p3_improve_large.py --ns 16 17 19 20 21 --hours 1.5
```

Long solver runs are sequenced rather than run concurrently, to avoid thermal
throttling on passively-cooled laptops.

## Method, in one paragraph

`verifier.py` is the single source of truth: it mirrors the official grader
exactly, including the easy-to-miss exterior-ring no-birth check, and every
claim in this repo round-trips through it. For the small-n proofs (n=8–11) we
run CP-SAT with two structurally different connectivity encodings — a
single-commodity flow (`cpsat_solver.py`) and a spanning-tree / parent-pointer
formulation (`cpsat_solver_st.py`) — and both return `OPTIMAL` with `bound =
objective` and *different* witness patterns, which rules out a shared
connectivity-encoding bug. We additionally cross-check with the ASP-2013
encoding via clingo (`run_solve.py`), and we use the published Chu–Stuckey
unconstrained ceiling whenever the verified connected witness matches it
(n=9). For n ≥ 13, CP-SAT runs in a budgeted, hint-seeded heuristic mode and
we report best-found honestly. See `LOG.md` for the full per-run record.

## Citation

If you use this work, please cite the CAISc 2026 paper (BibTeX entry will be
added once camera-ready DOIs are issued):

```
@inproceedings{phanindra2026connectedstilllife,
  title  = {Connected Maximum-Density Still Lifes: An Agentic Verifier + Proposer Loop},
  author = {Phanindra, Suraj},
  booktitle = {Proceedings of the Conference For AI Scientists (CAISc) 2026},
  year   = {2026}
}
```

## License

[MIT](LICENSE). The ASP-2013 encoding in `still_life-encoding.txt` and the
sample instances in `still_life-sample/` are credited to the ASP Competition
2013 Official Problem Suite; they are reproduced here unmodified for
cross-checking.
