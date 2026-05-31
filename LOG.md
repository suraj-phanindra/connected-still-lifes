# LOG — CAISc 2026 Connected Still Life

Running record of runs, failures, course corrections, seeds, and wall-clock.
Feeds the mandatory **AI-Involvement Checklist**; must reflect reality.
Operator: Claude Code (claude-opus-4-7 [1M]). Hardware: MacBook Air (M5), 4P+6E cores, 24 GB unified memory, fanless.

---

## 2026-05-29 — Phase 0: setup & sanity

### Environment
- Python 3.14.3 (`/opt/homebrew/bin/python3`) → project venv at `.venv/`
- Installed: `ortools==9.15.6755`, `clingo==5.8.0`, `numpy==2.4.6`
- macOS 26.4.1 (Build 25E253)

### Step 1 — Verifier golden tests (`python verifier.py`)
All four golden cases passed as expected:
- block 4×4 → VALID, 4 cells
- beehive 6×6 → VALID, 6 cells
- two disjoint blocks 7×7 → INVALID (disconnected)
- blinker 5×5 → INVALID (unstable)

Also independently re-verified the pre-existing `connected_stilllife_n8_best32_UNVERIFIED_OPT.json`: returns `(True, "VALID connected still life, 32 live cells")`.

### Step 2 — Restored the ASP-2013 clingo encoding
- `run_solve.py` had `ENC_PATH = "/mnt/user-data/uploads/still_life-encoding.txt"` (the prior sandbox path; does not exist on the M5).
- Operator copied `still_life-encoding.txt` and `still_life-sample/` into the project root.
- Patched `ENC_PATH` to a local `os.path.dirname(__file__) + "/still_life-encoding.txt"`.

### Step 3 — Patched `run_solve.py` for the M5
- Re-enabled `ctl.configuration.solve.parallel_mode` (was disabled for the 1-CPU sandbox); default 4 (= M5 performance-core count, deliberately not 10, to avoid thermal throttling on the fanless chassis).
- Added CLI: `ns`, `-t/--time-limit`, `-j/--threads`, `--seed`, `--verbose`.
- Set `ctl.configuration.solver.seed` for run-to-run reproducibility.
- Track an `improvements` trace `(t, cells, proven)` so we can see the SA-like ladder of improving models clingo produces.

### Step 3 — n=8 clingo run, with a subtle clingo API gotcha (recorded)
First long run reported `cells=32 | best-found (not proven) | 15.3s | verified OK`. The contradiction (elapsed 15s ≪ time limit 1200s but "not proven") flagged a likely API mis-read on our side, not a partial search.

Diagnostic (`async_=True`, 4 threads, seed 1, n=8):
```
elapsed=16.35s finished=True
satisfiable=True unsatisfiable=False unknown=False exhausted=True interrupted=False
last on_model: cells=32 proven=False cost=[-32]
```

**Root cause.** In clingo 5.8 under `solve(async_=True, on_model=...)`, `Model.optimality_proven` is NOT reliably set on the final improving model — the proof signal is the **`SolveResult.exhausted` flag**. With #maximize, monotonic search + `exhausted=True` + `satisfiable=True` + not `interrupted` ⇒ the best enumerated model IS the proven optimum.

**Fix.** Replaced the proven-optimal test in `run_solve.py`:
```python
proven_opt = bool(finished and res.satisfiable and res.exhausted and not res.interrupted)
```
(The old `best["proven"]` flag is kept in the improvements trace for diagnostics only.)

### n=8 RESULT — CLINGO, PROVEN OPTIMAL
| n | threads | seed | time limit | elapsed | cells | proven optimal? | verifier |
|---|--------:|-----:|-----------:|--------:|------:|:---------------:|:--------:|
| 8 |    4    |   1  |   120 s    | 15.6 s  | **32**| **YES**         | VALID    |
| 8 |    4    |   2  |   120 s    | 17.4 s  | **32**| **YES**         | VALID    |

Two seeds, two distinct 32-cell connected still-life witnesses (mirror images). Search space exhausted in both runs ⇒ **the connected maximum density at n=8 is exactly 32 cells** (density 32/64 = 50.00%).

Context: the unconstrained ceiling A055397(8) = 36 is proven optimal but is realized by **9 disjoint blocks** (CSPLib prob032), so the gap 36 − 32 = 4 is the *connectivity penalty* at n=8. The pre-existing `connected_stilllife_n8_best32_UNVERIFIED_OPT.json` matched the same value but had not been proven optimal (1-CPU sandbox).

**Saved artifact:** `connected_stilllife_n8_PROVEN_OPT_32.json` (seed-1 grid).

### n=9 RESULT — CLINGO + CEILING-MATCHING, PROVEN OPTIMAL

clingo found a verified **43-cell** connected still life for n=9 in **t=1.6 s** (4 threads). After 3 minutes the solver was still trying to prove no 44-cell solution exists — wasted CPU, because:

**Ceiling-matching argument.** The connected optimum is bounded above by the unconstrained optimum (adding connectivity restricts the feasible set, never grows it). Chu & Stuckey (2012) proved A055397(9) = 43 is the unconstrained optimum. Our verified connected witness reaches 43. Therefore:

```
43 ≤ connected-optimum(9)  [witness, verifier.py-validated]
connected-optimum(9) ≤ 43  [Chu-Stuckey 2012 unconstrained upper bound]
∴ connected-optimum(9) = 43.
```

This is a **proof of optimality without solver exhaustion**, valid whenever a verified connected witness matches the published A055397 ceiling. We adopted this as a standing rule: kill clingo once it hits the ceiling and move on.

| n | threads | seed | time-to-witness | cells | ceiling A055397(n) | matches ceiling? | proof | verifier |
|---|--------:|-----:|----------------:|------:|-------------------:|:----------------:|:-----:|:--------:|
| 9 |    4    |   1  |     1.6 s       | **43**|        43          |     **YES**      | ceiling-matching | VALID |

**Saved artifact:** `connected_stilllife_n9_PROVEN_OPT_43.json` (ceiling-matched).

### Scaffolded CP-SAT exact engine (`cpsat_solver.py`)
- Variables: `live`, `root`, `inject`, arc `flow` over 8-adjacency.
- Connectivity: single-commodity flow per user spec — virtual super-source injects `total_live` units at the chosen root (free root, `sum(root) ≤ 1`, `root → live`), each live cell consumes exactly 1, arc gating `flow ≤ n² · live(u)` and `flow ≤ n² · live(v)` on both endpoints.
- Stability + interior no-birth + **exterior-ring no-birth** all encoded to mirror `verifier.py` exactly.
- Returns the same dict shape as `run_solve.solve_n` for easy cross-checking.

### Phase 1 protocol going forward
For each n ∈ {10, 11, 13, 15} sequentially (clingo then CP-SAT per instance, never concurrent — thermal):
1. clingo with short budget; kill on ceiling-match (use ceiling-matching argument) or on exhaustion.
2. Then CP-SAT on same n; compare cells; both round-tripped through `verifier.py`.
3. Save the verified witness as JSON; label proven-optimal / best-found honestly; log here.

### Phase 1 results so far (the first per-n CONNECTED-optima table)

| n  | ceiling A055397 | **connected optimum** | gap | proof path | clingo wall | CP-SAT wall | JSON |
|---:|----------------:|----------------------:|----:|:-----------|:------------|:------------|:-----|
|  8 | 36 (9 disjoint blocks) | **32** PROVEN | 4 | clingo exhausted + CP-SAT OPTIMAL bound=32 | 15.6 s (seed 1), 17.4 s (seed 2) | 43.6 s | `connected_stilllife_n8_PROVEN_OPT_32.json` |
|  9 | 43 | **43** PROVEN | 0 | ceiling-matching (witness from clingo) + CP-SAT OPTIMAL bound=43 | 1.6 s (witness) | 6.3 s | `connected_stilllife_n9_PROVEN_OPT_43.json` |
| 10 | 54 | **53** PROVEN | 1 | CP-SAT OPTIMAL bound=53; clingo best-found 53 not proven | 5 min (best-found, not proven) | 44.0 s | `connected_stilllife_n10_PROVEN_OPT_53.json` |
| 11 | 64 (16 disjoint blocks) | **63** PROVEN | 1 | CP-SAT OPTIMAL bound=63; clingo best-found 62 (sub-optimal) | 5 min (best 62, not proven) | 322.9 s | `connected_stilllife_n11_PROVEN_OPT_63.json` |
| 13 | 90 | **87 best-found**, bound 89 (CP-SAT) | ≥ 1 | CP-SAT best-found 87 in 1800 s; bound 89 < ceiling 90 ⇒ optimum ∈ {87,88,89} | 5 min (best 85) | 1800 s (best 87, bound 89) | `connected_stilllife_n13_BEST_FOUND_87.json` |
| 15 | 119 | **116 best-found** (CP-SAT) | ≥ 3 | CP-SAT bound 122 is slack; Chu-Stuckey gives the tight upper bound 119 ⇒ optimum ∈ {116,…,119} | 5 min (best 112) | 2700 s (best 116, CP-SAT bound 122) | `connected_stilllife_n15_BEST_FOUND_116.json` |

### Phase 1 complete — verified per-n CONNECTED still life table

| n  | best verified | proven? | gap to ceiling | density |
|---:|--------------:|:-------:|---------------:|--------:|
|  8 | **32**        | yes (clingo exhaust + CP-SAT OPTIMAL) | 4 of 36 | 50.00% |
|  9 | **43**        | yes (ceiling-match + CP-SAT OPTIMAL)  | 0 of 43 | 53.09% |
| 10 | **53**        | yes (CP-SAT OPTIMAL bound 53)         | 1 of 54 | 53.00% |
| 11 | **63**        | yes (CP-SAT OPTIMAL bound 63)         | 1 of 64 | 52.07% |
| 13 | 87            | no (CP-SAT bound 89 → optimum ∈ [87,89]) | ≥ 1 of 90 | 51.48% |
| 15 | 116           | no (Chu-Stuckey ceiling 119 → optimum ∈ [116,119]) | ≥ 3 of 119 | 51.56% |

Phase 1 takeaways for the paper:
- We produced the **first per-n connected-optima table in the literature** for n = 8, 9, 10, 11 (all PROVEN OPTIMAL) and best-found-with-bounds for n = 13, 15.
- The CP-SAT single-commodity-flow connectivity encoding (free root, gated arcs, conservation = 1 per live cell) was the workhorse: it closed n = 8, 9, 10, 11 to OPTIMAL within minutes (n=11 in 5.4 min, others < 1 min). clingo's reachability encoding was competitive at n ≤ 9 for finding witnesses but stalled on both improvement (n=11: 62 vs CP-SAT 63) and proof at n ≥ 10.
- Densities are all just above 50%, consistent with Elkies' asymptotic bound.

### Phase 2 — SA for n ∈ {16, 17, 19, 20, 21}; stretch n ∈ {31, 32}

Scaffold in `sa_solver.py`:
- Hot loop in NumPy with verify-or-reject acceptance (Life constraints are too tight for in-place repair without complex bookkeeping).
- Seeds: `block_lattice` (period-3 2x2 blocks, valid but disconnected), `random_sparse` (high reject rate), `tile_n8` (lay our PROVEN_OPT 32-cell n=8 grid into the corners with row/col gaps as bridge real estate).
- Multi-restart driver; per-restart iteration budget configurable.
- JSON output in submission format.

Smoke test on n=8 first to confirm SA can find non-trivial valid grids before scaling up.

### Phase 2 reality check — SA hits Life's constraint tightness

The verify-or-reject SA on n=8 (smoke test, 4 restarts × 5000 iters) **never accepted a single move**:
- `block_lattice` init has 36 cells but is disconnected ⇒ invalid; SA's per-iteration verify() rejects this state.
- Every random-toggle or 3×3-rectangle proposal is also invalid (either destabilizes some existing live cell, causes a birth in or beside the affected region, or breaks/fails-to-create connectivity).
- For n=16 with the `embed_largest_fit` seed (= n=15 BEST_FOUND_116 placed at (0,0), already valid), there is no width-2 empty strip — only a 1-cell-wide border at row/col 15 — and no single-cell move can add live cells there without violating stability (an isolated live cell has 0 neighbors → unstable) or no-birth in the existing pattern.

Conclusion: **naïve verify-or-reject SA does not work** for connected still life. The constraint set is too tight for single-cell and small-rectangle moves to make valid progress; you need either smart repair operators (e.g., adding 2×2 stable atoms in cleared regions while preserving stability of neighbors), structured neighborhoods (slide a 2×2 block by one), or LNS with an exact CP-SAT sub-solver to fix small windows.

Per the user's locked plan ("Keep exact solvers off n>=16 -- that's the SA phase"), CP-SAT is not used for n ≥ 16. With smarter SA out of scope for the current time budget, the Phase 2 fallback is:

**embed-only baselines.** For each n ∈ {16, 17, 19, 20, 21, 31, 32}, save the n=15 BEST_FOUND_116 pattern embedded at (0, 0) of the n × n grid -- verifier-validated, connected, but very low density at the larger n. Saved JSONs:

| n  | best verified | density | ceiling | gap | source |
|---:|--------------:|--------:|--------:|----:|:-------|
| 16 | 116 | 45.31% | 136 | 20 | `connected_stilllife_n16_embed_only_116.json` |
| 17 | 116 | 40.14% | 152 | 36 | `connected_stilllife_n17_embed_only_116.json` |
| 19 | 116 | 32.13% | 190 | 74 | `connected_stilllife_n19_embed_only_116.json` |
| 20 | 116 | 29.00% | 210 | 94 | `connected_stilllife_n20_embed_only_116.json` |
| 21 | 116 | 26.30% | 232 | 116 | `connected_stilllife_n21_embed_only_116.json` |
| 31 | 116 | 12.07% | 497 | 381 | `connected_stilllife_n31_embed_only_116.json` |
| 32 | 116 | 11.33% | 531 | 415 | `connected_stilllife_n32_embed_only_116.json` |

These are valid-but-very-loose lower bounds. They are NOT meaningful "best-known" claims; the paper must label them transparently as embed-only baselines. The Phase-2-as-shipped contribution is the methodology (the scaffolded SA, the seed strategies attempted, and the diagnosis of *why* naïve SA fails on this problem) -- not these specific numbers.

### Decisions needed (where to invest remaining time)
1. **Smarter SA**: add-stable-atom (2×2 block insertion) + slide-block + LNS-with-CP-SAT-window. Significant authoring time; uncertain payoff in remaining budget.
2. **CP-SAT-as-heuristic for n ≥ 16** with the embedded pattern as a hint and a time budget (search heuristic, not optimality-proof attempt). The user's plan says "exact off n ≥ 16"; this is a possible loosening worth confirming.
3. **Ship now**: 4 PROVEN OPTIMAL + 2 BEST-FOUND-with-bounds + 7 embed-only baselines, with the methodology story foregrounded. Cleanest honest paper.

### Phase 1 triangulation via clingo (attempted, **inconclusive**)

Per user direction, ran a `feasibility.py` ceiling-feasibility check:
```
:- #count{X,Y : lives(X,Y), value(X), value(Y)} < target.
```
with the #maximize stripped, asking clingo to find ANY connected still life with cells ≥ target. Expected UNSAT for (n=10, target=54) and (n=11, target=64) ⇒ independent confirmation of CP-SAT's OPTIMAL bounds.

| case | budget | outcome |
|---|---|---|
| (n=10, target=54) | 600 s, 4 threads | **TIMEOUT** — no proof; clingo neither SAT nor UNSAT |
| (n=11, target=64) | 600 s, 4 threads | **TIMEOUT + clingo cancel hung** — had to `kill -9` after ~11 min |

clingo's reachability-encoded connectivity is too weak to close the upper-bound proof at this budget. The Phase 1 OPTIMAL claims remain held by CP-SAT alone (via the SCF connectivity encoding's `OPTIMAL`-status / `bound = obj = cells` certificates at n=8/9/10/11). This is honest but not the ideal cross-solver triangulation the plan envisioned.

(Within CP-SAT: the OPTIMAL-bound certificate IS a proof of `optimum ≤ bound`, so the Phase 1 numbers are not fragile — CP-SAT's certificate stands on its own. The "independent solver" check is what's missing.)

### Phase 2 — CP-SAT as a search heuristic for n ≥ 16
Per user direction, **relaxing the "exact off n ≥ 16" rule** to allow CP-SAT in NON-PROOF mode (time-budgeted search, never claimed proven). Plan:
1. Test n=16 first with a dense **block-lattice** AddHint (NOT the sparse 116-cell embed), 15-20 min budget.
2. If best-found > 116, sweep n ∈ {17, 19, 20, 21} with similar per-n budgets, all labeled best-found.
3. Skip n ∈ {31, 32} — leave embed-only baselines.

### Phase 2 results so far

| n  | hint                 | budget | best-found | status   | bound (CP-SAT) | tight ceiling | density | gap | JSON |
|---:|:---------------------|-------:|-----------:|:---------|---------------:|--------------:|--------:|----:|:-----|
| 16 | block_lattice (100c) | 900 s  | **131**    | FEASIBLE | 140 (slack)    | 136           | 51.17%  | ≥ 5  | `connected_stilllife_n16_cpsat_BEST_FOUND_131.json` |
| 17 | block_lattice (144c) | 900 s  | **138**    | FEASIBLE | 159 (slack)    | 152           | 47.75%  | ≥ 14 | `connected_stilllife_n17_cpsat_BEST_FOUND_138.json` |
| 19 | block_lattice (144c) | 900 s  | **179**    | FEASIBLE | 203 (slack)    | 190           | 49.58%  | ≥ 11 | `connected_stilllife_n19_cpsat_BEST_FOUND_179.json` |
| 20 | block_lattice (196c) | 900 s  | **195**    | FEASIBLE | 226 (slack)    | 210           | 48.75%  | ≥ 15 | `connected_stilllife_n20_cpsat_BEST_FOUND_195.json` |
| 21 | block_lattice (196c) | 900 s  | **221**    | FEASIBLE | 256 (slack)    | 232           | 50.11%  | ≥ 11 | `connected_stilllife_n21_cpsat_BEST_FOUND_221.json` |
| 31 | -                    | skip   | embed-only 116 | -    | -              | 497           | 12.07%  | 381  | `connected_stilllife_n31_embed_only_116.json` |
| 32 | -                    | skip   | embed-only 116 | -    | -              | 531           | 11.33%  | 415  | `connected_stilllife_n32_embed_only_116.json` |

CP-SAT-as-heuristic with the dense block-lattice hint dominated the embed-only baseline at every n ∈ {16, 17, 19, 20, 21}. Across the five n, the hint gives CP-SAT a high-density starting region (44.4% density block lattice) that is invalid only due to connectivity; CP-SAT then reshapes the lattice into a single connected component, losing a small number of cells (mostly at block boundaries where bridging cells force adjustments). Wall-clock: 15 min per n, 4 P-cores.

In all five cases, CP-SAT's own bound is slack vs. the Chu-Stuckey ceiling (e.g., bound 256 vs. ceiling 232 at n=21), so the tight upper bound for the gap calculation is the published unconstrained ceiling, not CP-SAT's.

## Final per-n CONNECTED still life table (CAISc 2026 submission)

| n  | best verified | density | ceiling | proven? | source label |
|---:|--------------:|--------:|--------:|:-------:|:-------------|
|  8 | **32**        | 50.00%  |  36     | yes     | PROVEN_OPT (clingo exhaust + CP-SAT OPTIMAL) |
|  9 | **43**        | 53.09%  |  43     | yes     | PROVEN_OPT (ceiling-matching + CP-SAT OPTIMAL) |
| 10 | **53**        | 53.00%  |  54     | yes     | PROVEN_OPT (CP-SAT OPTIMAL bound=53) |
| 11 | **63**        | 52.07%  |  64     | yes     | PROVEN_OPT (CP-SAT OPTIMAL bound=63) |
| 13 | 87            | 51.48%  |  90     | no      | BEST_FOUND (CP-SAT bound 89 → optimum ∈ [87,89]) |
| 15 | 116           | 51.56%  | 119     | no      | BEST_FOUND (Chu-Stuckey gives optimum ∈ [116,119]) |
| 16 | 131           | 51.17%  | 136     | no      | BEST_FOUND (CP-SAT-as-heuristic, 15 min) |
| 17 | 138           | 47.75%  | 152     | no      | BEST_FOUND (CP-SAT-as-heuristic, 15 min) |
| 19 | 179           | 49.58%  | 190     | no      | BEST_FOUND (CP-SAT-as-heuristic, 15 min) |
| 20 | 195           | 48.75%  | 210     | no      | BEST_FOUND (CP-SAT-as-heuristic, 15 min) |
| 21 | 221           | 50.11%  | 232     | no      | BEST_FOUND (CP-SAT-as-heuristic, 15 min) |
| 31 | 116           | 12.07%  | 497     | no      | EMBED_ONLY (n=15 BEST_FOUND_116 embedded) |
| 32 | 116           | 11.33%  | 531     | no      | EMBED_ONLY (n=15 BEST_FOUND_116 embedded) |

Densities for n ∈ {8 … 21}: 47.8 % – 53.1 %, all close to the Elkies asymptotic infinite-lattice bound (½) and consistent with the small-n PROVEN OPTIMAL band.
Densities for n ∈ {31, 32}: 12 % and 11 % — the placeholder embed-only baselines are very loose; SA with structured stable-atom moves or hint-based CP-SAT-as-heuristic would close most of that gap. Out of scope for this submission's budget; flagged explicitly in the paper as future work.

### Methodological contribution (for the paper)
1. **Verifier-as-oracle discipline.** Every claim round-trips through `verifier.verify(grid, n, claimed_cells)`, which mirrors the official grader byte-for-byte including the easy-to-miss exterior-ring birth check.
2. **Two complementary deterministic solvers** (clingo with the ASP-2013 encoding + CP-SAT with our SCF connectivity encoding), each cross-checking the other where both close. Where solvers disagree on quality (e.g., n=11: clingo best 62, CP-SAT OPTIMAL 63), the verifier independently validates the better witness.
3. **Two complementary proof tools for optimality:** solver exhaustion (clingo `exhausted=True` for n=8; CP-SAT `OPTIMAL` with `bound = obj` for n=10, 11) and the **ceiling-matching argument** (Chu-Stuckey unconstrained ceiling = verified connected witness ⇒ proof, no solver exhaustion required; used for n=9).
4. **CP-SAT-as-heuristic in non-proof mode for n ≥ 16**, with a dense block-lattice AddHint. This is the agentic loop in microcosm: a deterministic search engine + a domain-aware proposal (the hint), orchestrated by the LLM agent (this session) to set the budget per box and label results honestly.
5. **Honest negative results.** Naive verify-or-reject SA accepts zero moves on n=16 with a near-optimal seed; the diagnosis is reported, not papered over. clingo's reachability connectivity can't close the upper-bound proof at the per-instance budgets we tried (TIMEOUT on n=10 target=54; cancel-hang on n=11 target=64).

## 2026-05-30 — Strengthening the rigorous core

### P1(a) — Triangulate Phase 1 with a SECOND, independent CP-SAT connectivity encoding

New solver `cpsat_solver_st.py`. Stability + interior no-birth + exterior-ring no-birth: **byte-identical to `cpsat_solver.py`** (the SCF model). Only the connectivity model differs:

- **SCF (cpsat_solver.py)**: virtual super-source, arc flows over 8-adjacency, arc-gating on both endpoints live, conservation = 1 per live cell.
- **Spanning-tree (cpsat_solver_st.py)**: `parent_dir[(c, c')]` Booleans (c' is parent of c) + integer `depth[c]` ∈ [0, n²-1]. Each live cell is either the root (depth 0) or has exactly one in-box live parent; depth strictly increases along parent edges ⇒ no cycles ⇒ rooted spanning tree ⇒ connectivity.

| n | encoding | status | cells | elapsed | bound = obj? | witness pattern |
|---|---------|--------|------:|--------:|:------------:|:----------------|
|  8 | SCF (existing) | OPTIMAL | 32 | 43.6 s | yes | one shape |
|  8 | spanning-tree (new) | OPTIMAL | 32 | **1.3 s** | yes | DIFFERENT shape (see `connected_stilllife_n8_cpsat_ST_*.json` if --save-json) |
| 10 | SCF (existing) | OPTIMAL | 53 | 44.0 s | yes | one shape |
| 10 | spanning-tree (new) | OPTIMAL | 53 | **5.0 s** | yes | DIFFERENT shape (`connected_stilllife_n10_cpsat_ST_PROVEN_OPT_53.json`) |
| 11 | SCF (existing) | OPTIMAL | 63 | 322.9 s | yes | one shape |
| 11 | spanning-tree (new) | OPTIMAL | 63 | **116.0 s** | yes | DIFFERENT shape (`connected_stilllife_n11_cpsat_ST_PROVEN_OPT_63.json`) |

**Verdict (P1(a))**: triangulation succeeds. Two structurally different connectivity encodings — one flow-based, one tree-based — independently arrive at the same `OPTIMAL` value with the same `bound = obj` certificate at n=8/10/11. A shared connectivity-encoding bug producing this consistent answer is essentially ruled out. Side benefit: ST is markedly faster than SCF on this problem (≥3× at every n tested).

### P1(b) — clingo stability-only enumeration at the ceiling
New script `enum_at_ceiling.py`. Strips clingo's `reached/2` connectedness rules and adds two integrity constraints to force `#count{lives} == target` exactly. With `--models=0`, clingo enumerates every still life of the given cardinality, and Python checks each for 8-connectivity via `verifier.py`. If every enumerated witness is disconnected AND search exhausts, **no connected still life with `target` cells exists** — proof from a non-CP-SAT engine.

Smoke test (n=8, target=36 = the unconstrained ceiling, known disconnected as the 9-block lattice):
- 6.2 s, EXHAUSTED, 1 model, 0 connected, 1 disconnected.
- Verdict logged: PROVEN connected-optimum(8) < 36. (Sanity-checks the encoding.)

Real cases:
- **n=10 target=54, 30 min budget** — INCONCLUSIVE on exhaustion; **directionally consistent** with optimum=53: clingo enumerated **364 stability-only models in 1800 s, EVERY one disconnected** (0 connected, 364 disconnected, 0 unexpected verify failures). Search did not exhaust within the budget, so this is not yet a proof — but 364/364 disconnected without ever finding a connected witness is strong corroborating evidence; per the user's plan, recorded honestly and P1(a) still stands.
- **n=11 target=64, 60 min budget** — INCONCLUSIVE on exhaustion; **directionally consistent** with optimum=63: 2 stability-only models in 3600 s, BOTH disconnected (0 connected, 2 disconnected). Search did not exhaust. clingo's enumeration is much slower at n=11 than n=10 because the 64-cell stability constraint is tighter (16-block lattice and variants), and the still-life encoding without connectivity gives fewer per-second propagation wins. Same honest recording as n=10.

**Summary of P1 triangulation**: optimality claims at n=8, 10, 11 are now backed by:
- Two independent CP-SAT encodings (SCF flow + spanning-tree parent-pointer + depth), both returning `OPTIMAL` with `bound = obj = cells`.
- Partial clingo enumeration (366 total stability-only models across n=10/11 at the ceiling, every one disconnected) — corroborating but not a proof on its own.

For the paper: present (a) as the primary independent confirmation (different encoding family, same OPTIMAL value, same `bound=obj` certificate); present (b) as supporting evidence with explicit "did-not-exhaust" caveat.

### P2 — Close the n=13 gap

`p2_close_n13.py` ran three sequenced strategies, 1 h each (3 h total):
1. **SCF + block_lattice (64-cell) hint** → cells=88, FEASIBLE, bound 89, wall 3600 s.
2. **Spanning-tree + block_lattice hint** → cells=88, FEASIBLE, bound 89, wall 3601 s.
3. **SCF + warm-start from the 88-cell witness above** → cells=88, FEASIBLE, bound 89, wall 3601 s.

All three independently improve over the previous Phase 1 BEST_FOUND_87, and all three converge on the **same value 88** without closing the upper bound. Saved JSONs (all verifier-valid):
- `connected_stilllife_n13_p2_SCF_blocklattice_BEST_FOUND_88.json`
- `connected_stilllife_n13_p2_ST_blocklattice_BEST_FOUND_88.json`
- `connected_stilllife_n13_p2_SCF_warmstart_BEST_FOUND_88.json`

**New bound: connected-optimum(13) ∈ {88, 89}** (was {87, 88, 89}). Witness 88 is on the table; CP-SAT's bound certificate gives ≤ 89. The fact that two different connectivity encodings AND a warm-start each terminate at exactly 88 with bound 89 is a strong (informal) indication that 88 IS the optimum — but to claim it we'd need either a tighter encoding or a much longer single run. Recorded honestly as best-found.

n=15 stretch (close [116, 119]): SKIPPED per the user's "lower odds, fine to leave bounded" note. The CPU budget is better spent on P3.

### P3 — Improve n=16-21 best-found
`p3_improve_large.py`: warm-start from the highest-cell-count verifier-valid pattern on disk (if denser than block_lattice), else use block_lattice. Each n given a 1.5 h budget, sequential (no concurrent solvers). Save improved witnesses under NEW filenames.

| n  | hint chosen (denser of two)        | result | prior best | Δ    | CP-SAT bound | density |
|---:|:-----------------------------------|-------:|-----------:|-----:|-------------:|--------:|
| 16 | warm-start (131)                   | 131    | 131        |  0   | 139          | 51.17% |
| 17 | block_lattice (144)                | **147**| 138        | +9   | 157          | 50.87% |
| 19 | warm-start (179)                   | 179    | 179        |  0   | 198          | 49.58% |
| 20 | block_lattice (196)                | **201**| 195        | +6   | 223          | 50.25% |
| 21 | warm-start (221)                   | 219    | 221        | −2 (not saved) | 248 | 50.11% (unchanged) |

Saved: `connected_stilllife_n17_p3_cpsat_BEST_FOUND_147.json`, `connected_stilllife_n20_p3_cpsat_BEST_FOUND_201.json` (both verifier-valid).

**Pattern.** Improvements came on the two n where block_lattice was the chosen hint (n=17, n=20); warm-start runs (n=16, n=19, n=21) sat at the prior optimum. block_lattice nudges CP-SAT to a different local-search basin; warm-start biases too strongly toward the existing solution and rediscovers it. For the paper: this is a clean data point about hint diversity in CP-SAT-as-heuristic on tight cell-automaton constraints.

P4 (n=31/32 stretch): SKIPPED per the user's instruction (insufficient time remaining for it to matter).

## Final per-n CONNECTED still life table (CAISc 2026 submission, locked)

| n  | best verified | density | ceiling | gap | source label |
|---:|--------------:|--------:|--------:|----:|:-------------|
|  8 | **32**        | 50.00%  |  36     |  4  | PROVEN_OPT (clingo exhaust + CP-SAT SCF OPTIMAL + CP-SAT ST OPTIMAL) |
|  9 | **43**        | 53.09%  |  43     |  0  | PROVEN_OPT (ceiling-matching + CP-SAT SCF OPTIMAL) |
| 10 | **53**        | 53.00%  |  54     |  1  | PROVEN_OPT (CP-SAT SCF OPTIMAL + CP-SAT ST OPTIMAL) |
| 11 | **63**        | 52.07%  |  64     |  1  | PROVEN_OPT (CP-SAT SCF OPTIMAL + CP-SAT ST OPTIMAL) |
| 13 | 88            | 52.07%  |  90     | ≥1  | BEST_FOUND (CP-SAT bound 89 ⇒ optimum ∈ {88, 89}); P2 improvement from prior 87 |
| 15 | 116           | 51.56%  | 119     | ≥3  | BEST_FOUND (Chu-Stuckey ⇒ optimum ∈ [116, 119]) |
| 16 | 131           | 51.17%  | 136     | ≥5  | BEST_FOUND (CP-SAT-as-heuristic, block_lattice hint) |
| 17 | 147           | 50.87%  | 152     | ≥5  | BEST_FOUND (CP-SAT-as-heuristic, block_lattice hint, P3 improvement from prior 138) |
| 19 | 179           | 49.58%  | 190     | ≥11 | BEST_FOUND (CP-SAT-as-heuristic, block_lattice hint) |
| 20 | 201           | 50.25%  | 210     | ≥9  | BEST_FOUND (CP-SAT-as-heuristic, block_lattice hint, P3 improvement from prior 195) |
| 21 | 221           | 50.11%  | 232     | ≥11 | BEST_FOUND (CP-SAT-as-heuristic, block_lattice hint) |
| 31 | 116           | 12.07%  | 497     | ≥381 | EMBED_ONLY (placeholder — not a real best-known; P4 skipped) |
| 32 | 116           | 11.33%  | 531     | ≥415 | EMBED_ONLY (placeholder — not a real best-known; P4 skipped) |

n ∈ {8 … 21}: densities 49.6 % – 53.1 %, all within ~3 percentage points of the Elkies asymptotic infinite-lattice bound (½). The connectivity penalty (ceiling − best) is small (0 – 11) and grows slowly with n.

n ∈ {31, 32}: very low density placeholders; the paper must label them explicitly as embed-only baselines, not a real best-known, with future work the natural next step.

Key observations:
- **CP-SAT dominates clingo on this problem at n ≥ 10.** clingo finds tight witnesses quickly at small n but stalls on improving moves and on proofs. CP-SAT's LCG-based search with the SCF connectivity encoding closes the gap to OPTIMAL cleanly. This is a paper-worthy datapoint about which solver family handles the connectivity-augmented Life encoding better.
- **All four proven values are below or equal to the unconstrained ceiling.** Three of the four (n=8, 10, 11) are STRICTLY less — the connectivity penalty is nonzero. n=9 has zero penalty.
- **The pre-existing 32-cell n=8 file `connected_stilllife_n8_best32_UNVERIFIED_OPT.json` is now confirmed to have been at the true optimum** (= 32), but it lacked the proof; the new file carries the proven label.

### Phase 1 reproducibility checklist
- Seeds: clingo `--seed 1` (and a `--seed 2` confirmation for n=8). CP-SAT `random_seed=1`.
- Threads: 4 (M5 performance cores). clingo `parallel_mode='4'`; CP-SAT `num_search_workers=4`.
- Time budgets per n: documented in LOG above.
- Witnesses: saved as `connected_stilllife_n{N}_PROVEN_OPT_{cells}.json` in the submission format.
- Independent re-verification: every saved JSON passes `verifier.verify(grid, n, claimed_cells)`.
