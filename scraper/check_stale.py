#!/usr/bin/env python3
"""check_stale.py - fail loudly if any chain has not COMPLETED a scrape for days.

The alert job only fires when a job fails, so a chain that quietly stops
finishing (site blocking us, sitemap changed, a bug that never reaches the
completion marker) never trips anything: the weeks-long "completion marker
never written" bug went unnoticed for exactly this reason. Each chain's
data/latest/.<chain>-complete holds the date of its last full pass; this
exits 1 (-> continue-check job fails -> the alert job opens an issue) when
any is older than MAX_AGE_DAYS or missing.

Country-agnostic: the chain list is auto-discovered from data/latest
(per-chain *.jsonl files), so the same script works in every *-priser repo.
A CHAINS env var (comma/space separated) overrides discovery if set.

Skousen legitimately needs ~10 runner-hours per pass (it rate-limits us to
roughly 10 requests/minute), i.e. two runs, so 'today' is too strict; 3 days
only trips on a real, sustained stall.
"""
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST = os.path.join(ROOT, "data", "latest")

# canonical fallback (dk-byggepriser itself) — used only if nothing else found
DEFAULT_CHAINS = ["silvan", "xlbyg", "stark", "bauhaus", "davidsen",
                  "fog", "haraldnyborg", "power", "skousen"]
MAX_AGE_DAYS = 3


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
    today = date.today()
    stale = []
    for chain in discover_chains():
        marker = os.path.join(LATEST, f".{chain}-complete")
        try:
            last = date.fromisoformat(open(marker).read().strip())
            age = (today - last).days
        except (OSError, ValueError):
            stale.append(f"{chain} (no valid completion marker)")
            continue
        if age > MAX_AGE_DAYS:
            stale.append(f"{chain} (last full pass {last}, {age} days ago)")
    if stale:
        print("::error::chains with no completed scrape in >%d days: %s"
              % (MAX_AGE_DAYS, "; ".join(stale)))
        sys.exit(1)
    print("all chains completed a full pass within %d days" % MAX_AGE_DAYS)


if __name__ == "__main__":
    main()
