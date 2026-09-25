#!/usr/bin/env python3
"""check_incomplete.py — find chains that lack a completion marker (or whose
marker is older than today) and emit them as a comma-list for the workflow.

Country-agnostic: the chain list is auto-discovered from data/latest
(per-chain *.jsonl files), so the same script works in every *-priser repo.
A CHAINS env var (comma/space separated) overrides discovery if set.

Expected catalog sizes only exist for the Danish chains; unknown chains fall
back to marker-only (no row-count floor) until a real baseline is known.

Exit codes: 0 = all chains complete, 2 = some incomplete (workflow continues).
"""
import os
import re
import sys
import json
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST = os.path.join(ROOT, "data", "latest")

# canonical fallback (dk-byggepriser itself) — used only if nothing else found
DEFAULT_CHAINS = ["silvan", "xlbyg", "stark", "bauhaus", "davidsen",
                  "fog", "haraldnyborg", "power", "skousen"]

# known catalog sizes (approximate, from verified production runs) — a chain
# whose snapshot holds <60% of this is treated as incomplete even with a marker
EXPECTED = {
    "silvan": 39000, "xlbyg": 45000, "stark": 20000, "bauhaus": 22000,
    "davidsen": 26000, "fog": 29000, "haraldnyborg": 10800, "power": 28000,
    "skousen": 5300,
}


def discover_chains():
    env = os.environ.get("CHAINS", "")
    if env.strip():
        return [c.strip() for c in re.split(r"[,\s]+", env) if c.strip()]
    chains = set()
    if os.path.isdir(LATEST):
        for fn in os.listdir(LATEST):
            if fn.startswith(".") or fn in ("prices.jsonl", "scrape_state.json"):
                continue
            if not fn.endswith(".jsonl"):
                continue
            chains.add(fn[:-len(".jsonl")])
    return sorted(chains) if chains else list(DEFAULT_CHAINS)


def main():
    today = date.today().isoformat()
    incomplete = []
    detail = {}
    for chain in discover_chains():
        marker = os.path.join(LATEST, f".{chain}-complete")
        path = os.path.join(LATEST, f"{chain}.jsonl")
        n = 0
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                n = sum(1 for _ in f)
        floor = EXPECTED.get(chain, 0) * 0.6   # 0 for unknown chains = marker-only
        ok = (os.path.exists(marker) and open(marker).read().strip() == today
              and n >= floor)
        detail[chain] = {"rows": n, "complete": ok}
        if not ok:
            incomplete.append(chain)
    json.dump({"date": today, "detail": detail},
              open(os.path.join(LATEST, "completion.json"), "w"), indent=1)
    print("incomplete:", ",".join(incomplete) if incomplete else "(none)")
    sys.exit(2 if incomplete else 0)


if __name__ == "__main__":
    main()
