#!/usr/bin/env python3
"""Merge per-chain snapshots (written by parallel CI jobs) into the final
feed: prices.jsonl, comparison.json, summary.json, ages.json."""
import os
import sys
import json
import glob
import gzip
import re
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from build_comparison import main as build_comparison  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAINS = ["cpo_us"]
LATEST = os.path.join(ROOT, "data", "latest")


def main():
    today = date.today().isoformat()
    merged_path = os.path.join(LATEST, "prices.jsonl")
    merged_gz_path = merged_path + ".gz"
    # The collapse guard below needs yesterday's row count, but prices.jsonl
    # itself is no longer committed (see the workflow's own comment - it hit
    # GitHub's 50MB warning and kept growing) - only prices.jsonl.gz survives
    # between runs now. Decompress THAT to get a real prev_size instead of
    # silently reading 0 every time (which would disable this guard for good,
    # exactly the kind of always-passes-because-the-baseline-is-wrong bug
    # already found and fixed once in run_daily.py's own collapse guard).
    prev_size = 0
    if os.path.exists(merged_gz_path):
        with gzip.open(merged_gz_path, "rt", encoding="utf-8") as f:
            prev_size = sum(1 for _ in f)
    elif os.path.exists(merged_path):
        with open(merged_path, encoding="utf-8") as f:
            prev_size = sum(1 for _ in f)
    seen, n, dupes = set(), 0, 0
    with open(merged_path, "w", encoding="utf-8") as out:
        for chain in CHAINS:
            p = os.path.join(LATEST, f"{chain}.jsonl")
            if not os.path.exists(p):
                continue
            with open(p, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    key = (r.get("chain"), r.get("sku") or r.get("url"))
                    if key in seen:
                        dupes += 1
                        continue
                    seen.add(key)
                    out.write(line)
                    n += 1

    # merge per-chain summary files
    summary = {}
    for sp in glob.glob(os.path.join(LATEST, "summary-*.json")):
        try:
            d = json.load(open(sp))
        except json.JSONDecodeError:
            continue
        summary.update(d.get("chains", {}))

    json.dump({"date": today, "total_rows": n, "chains": summary},
              open(os.path.join(LATEST, "summary.json"), "w"), indent=1)

    # staleness ledger
    ages_path = os.path.join(LATEST, "ages.json")
    ages = {}
    if os.path.exists(ages_path):
        try:
            ages = json.load(open(ages_path))
        except json.JSONDecodeError:
            ages = {}
    for chain in CHAINS:
        d = summary.get(chain, {})
        if "products" in d:  # success this run
            ages[chain] = today
    json.dump(ages, open(ages_path, "w"), indent=1)

    if n == 0 or (prev_size and n < prev_size * 0.3):
        raise SystemExit(f"merge collapse guard: {n} rows vs {prev_size} before — keeping previous feed")
    build_comparison()
    build_status_page()
    pruned = prune_old_history()
    print(f"merged {n} rows ({dupes} dupes dropped); comparison rebuilt"
          + (f"; pruned {pruned} history files >120d old" if pruned else ""))


HISTORY_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")


def prune_old_history(max_age_days=120, today=None):
    """Delete data/history/<chain>/<date>.jsonl files older than max_age_days.

    Was previously `find data/history -name "*.jsonl" -mtime +120 -delete`
    in the workflow - looked reasonable, never actually worked. Every CI
    job does a fresh `actions/checkout`, and git does not (and cannot)
    preserve original commit timestamps as file mtimes - a freshly checked
    out file's mtime is always "now", the moment of that checkout, on
    every single run. `-mtime +120` was therefore comparing "now" against
    "now" every single day, forever, and could never delete anything -
    confirmed: data/history has commits going back to 2026-08-28 that were
    never once pruned despite this running as part of every merge job
    since. Fixed by reading the real date directly from each file's own
    name (data/history/<chain>/<YYYY-MM-DD>.jsonl) instead of trusting
    filesystem metadata that git checkouts make meaningless.
    """
    if today is None:
        today = date.today()
    cutoff = today - timedelta(days=max_age_days)
    removed = 0
    history_root = os.path.join(LATEST, "..", "history")
    if not os.path.isdir(history_root):
        return removed
    for chain_dir in os.listdir(history_root):
        full_dir = os.path.join(history_root, chain_dir)
        if not os.path.isdir(full_dir):
            continue
        for fname in os.listdir(full_dir):
            m = HISTORY_DATE_RE.match(fname)
            if not m:
                continue
            try:
                file_date = date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if file_date < cutoff:
                os.remove(os.path.join(full_dir, fname))
                removed += 1
    return removed





def build_status_page():
    """Tiny zero-JS status page: system health + browsing the freshest prices."""
    import html as H
    from datetime import datetime
    try:
        summary = json.load(open(os.path.join(LATEST, "summary.json")))
    except Exception:
        summary = {}
    try:
        ages = json.load(open(os.path.join(LATEST, "ages.json")))
    except Exception:
        ages = {}
    rows = []
    src = os.path.join(LATEST, "prices.jsonl")
    if os.path.exists(src):
        with open(src, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    # cheapest 100 by name for a browsable taste of the catalog
    rows.sort(key=lambda r: (r.get("name") or "").lower())
    trs = "".join(
        f"<tr><td>{H.escape(str(r.get('name','')))}</td>"
        f"<td>{r.get('price')} kr</td>"
        f"<td>{r.get('chain')}</td>"
        f"<td>{H.escape(str(r.get('unit') or ''))}</td></tr>"
        for r in rows[:100])
    chains_tr = "".join(
        f"<tr><td>{c}</td><td>{d.get('products','—')}</td>"
        f"<td>{ages.get(c,'—')}</td></tr>"
        for c, d in sorted(summary.get("chains", {}).items()))
    page = f"""<!doctype html><html lang=da><meta charset=utf-8>
<title>DK Byggepriser — status</title>
<style>body{{font-family:-apple-system,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:6px 10px;text-align:left}}
h1{{font-size:1.4rem}} .muted{{color:#666}}</style>
<h1>DK Byggepriser</h1>
<p class=muted>Opdateret: {summary.get('date','?')} · {summary.get('total_rows', len(rows)):,} varer ·
Priser er inkl. moms fra offentlige webshops. Kilde: data/latest/prices.jsonl</p>
<h2>Kæder</h2><table><tr><th>Kæde</th><th>Varer</th><th>Seneste fulde snapshot</th></tr>{chains_tr}</table>
<h2>Eksempler (alfabetisk, første 100)</h2>
<table><tr><th>Vare</th><th>Pris</th><th>Kæde</th><th>Enhed</th></tr>{trs}</table>"""
    with open(os.path.join(LATEST, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    print("status page written")


if __name__ == "__main__":
    main()
