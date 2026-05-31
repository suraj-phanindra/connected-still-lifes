"""Walk every connected_stilllife_n*_*.json in the project, re-verify each,
and print a clean per-n summary table -- our running per-n connected-optima
table. Always re-validates with verifier.verify; never trusts a JSON's
claimed cell count without checking.
"""
import glob
import json
import os
import re

from verifier import verify

CEILINGS = {  # OEIS A055397, proven optimal (Chu & Stuckey 2012)
    8: 36, 9: 43, 10: 54, 11: 64, 13: 90, 15: 119,
    16: 136, 17: 152, 19: 190, 20: 210, 21: 232, 31: 497, 32: 531,
}

HERE = os.path.dirname(os.path.abspath(__file__))

def label_from_filename(path: str) -> str:
    name = os.path.basename(path)
    m = re.match(r"connected_stilllife_n(\d+)_(.*?)\.json", name)
    if not m:
        return "?"
    return m.group(2)


def main():
    paths = sorted(glob.glob(os.path.join(HERE, "connected_stilllife_n*.json")))
    rows = []
    for p in paths:
        try:
            d = json.load(open(p))
        except Exception as e:
            rows.append({"file": os.path.basename(p), "ok": False, "msg": str(e)})
            continue
        n = d.get("n")
        claimed = d.get("claimed_cells")
        grid = d.get("grid")
        ok, msg = verify(grid, n, claimed)
        rows.append({
            "file": os.path.basename(p),
            "n": n,
            "cells": claimed,
            "ceiling": CEILINGS.get(n, "?"),
            "gap": (CEILINGS.get(n, 0) - claimed if claimed and CEILINGS.get(n) else None),
            "label": label_from_filename(p),
            "ok": ok,
            "msg": msg,
        })

    rows.sort(key=lambda r: (r.get("n") or 0, -(r.get("cells") or 0), r["file"]))

    # Aggregate best-verified per n
    best = {}
    for r in rows:
        if not r.get("ok"):
            continue
        n = r["n"]
        if (n not in best) or (r["cells"] > best[n]["cells"]):
            best[n] = r

    print("\n=== ALL ARTIFACTS (re-verified) ===")
    print(f"{'file':<60} {'n':>3} {'cells':>5} {'ceiling':>7} {'gap':>4}  verify")
    for r in rows:
        cells = r.get("cells", "-")
        ceil = r.get("ceiling", "-")
        gap = r.get("gap", "-")
        ok = "OK" if r.get("ok") else f"FAIL: {r.get('msg')}"
        print(f"{r['file']:<60} {str(r.get('n','-')):>3} {str(cells):>5} {str(ceil):>7} {str(gap):>4}  {ok}")

    print("\n=== BEST VERIFIED CONNECTED VALUE PER n ===")
    print(f"{'n':>3} {'cells':>5} {'density':>8} {'ceiling':>7} {'gap':>4}  source")
    for n in sorted(best.keys()):
        r = best[n]
        density = (r["cells"] / (n * n)) * 100.0
        print(f"{n:>3} {r['cells']:>5} {density:>7.2f}% {r['ceiling']:>7} {r['gap']:>4}  {r['file']}")


if __name__ == "__main__":
    main()
