#!/usr/bin/env python3
"""check_incomplete.py — find chains that lack a completion marker (or whose
marker is older than today) and emit them as a comma-list for the workflow.

Exit codes: 0 = all chains complete, 2 = some incomplete (workflow continues).
"""
import os
import sys
import json
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST = os.path.join(ROOT, "data", "latest")
CHAINS = ["ace_us"]

# known catalog sizes (approximate, from verified sources) — a chain whose
# snapshot holds <60% of this is treated as incomplete even with a marker
# Verified real catalog sizes (from completed production runs):
EXPECTED = {
    "ace_us": 5000
}


def main():
    today = date.today().isoformat()
    incomplete = []
    detail = {}
    for chain in CHAINS:
        marker = os.path.join(LATEST, f".{chain}-complete")
        path = os.path.join(LATEST, f"{chain}.jsonl")
        n = 0
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                n = sum(1 for _ in f)
        ok = (os.path.exists(marker) and open(marker).read().strip() == today
              and n >= EXPECTED.get(chain, 0) * 0.6)
        detail[chain] = {"rows": n, "complete": ok}
        if not ok:
            incomplete.append(chain)
    json.dump({"date": today, "detail": detail},
              open(os.path.join(LATEST, "completion.json"), "w"), indent=1)
    print("incomplete:", ",".join(incomplete) if incomplete else "(none)")
    sys.exit(2 if incomplete else 0)


if __name__ == "__main__":
    main()
