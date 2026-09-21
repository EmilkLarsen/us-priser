#!/usr/bin/env python3
"""Full-refresh strategy for CI time limits.

A complete catalog pass takes hours, so the nightly job runs chains in
PARALLEL JOBS (one per chain, matrix strategy) — each chain easily fits
its own 300-min limit, and GitHub runs them simultaneously on free
public runners. run_daily.py gets --only <chain> to support this.
"""
import sys
import os
import json
import time
import inspect
import importlib
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAINS = ["ace_us"]


def load_prev(chain):
    path = os.path.join(ROOT, "data", "latest", f"{chain}.jsonl")
    prev = {}
    if not os.path.exists(path):
        return prev
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = r.get("sku") or r.get("url")
            prev[key] = r
    return prev


# Expiry of delisted products. A row that a COMPLETE pass no longer
# refreshes gets `missing_since: <date>` (fresh rows never carry the field,
# so day-to-day diffs stay tiny); if it is still missing 14 days later it is
# dropped from the catalog. Previously rows were retained forever, so a
# delisted product kept its last price in the app indefinitely (~600 such rows
# at haraldnyborg alone by 2026-09-21).
EXPIRE_AFTER_DAYS = 14
# If a single complete pass leaves more than this share of a chain missing,
# treat it as a broken scrape (sitemap change, parser regression, block) and
# touch nothing - real delistings never remove 15% of a catalog at once.
MAX_MISSING_FRACTION = 0.15
# Chains whose daily pass only covers a rotating slice of the catalog: rows
# outside today's slice are "missing" by design, so no expiry applies.
ROTATING_CHAINS = {"stark"}


def expire_missing(existing, fresh_keys, today):
    """Stamp/drop rows a complete pass did not refresh. Mutates `existing`.
    Returns (newly_missing, dropped, skipped_reason)."""
    missing = [k for k in existing if k not in fresh_keys]
    if not missing:
        return 0, 0, None
    if len(missing) > MAX_MISSING_FRACTION * len(existing):
        return 0, 0, f"{len(missing)} of {len(existing)} rows missing (> {MAX_MISSING_FRACTION:.0%})"
    stamped = dropped = 0
    for k in missing:
        row = existing[k]
        since = row.get("missing_since")
        if not since:
            row["missing_since"] = today
            stamped += 1
            continue
        try:
            age = (date.fromisoformat(today) - date.fromisoformat(since)).days
        except ValueError:
            row["missing_since"] = today
            continue
        if age >= EXPIRE_AFTER_DAYS:
            del existing[k]
            dropped += 1
    return stamped, dropped, None


def main():
    args = sys.argv[1:]
    limit = None
    only = None
    if "--only" in args:
        only = args[args.index("--only") + 1]
        args = args[:args.index("--only")] + args[args.index("--only") + 2:]
    limit = int(args[0]) if args else None
    chains = [only] if only else CHAINS
    if only and only not in CHAINS:
        raise SystemExit(f"unknown chain: {only}")

    today = date.today().isoformat()
    summary = {}

    # A soft internal cutoff so silvan/xlbyg/stark's checkpointed scrape
    # exits normally with time to spare before the JOB's own hard timeout
    # (350 min in daily-prices.yml) SIGKILLs it - a run killed externally
    # never reaches "Commit snapshot", so nothing it did survives (see
    # scrape_with_checkpoint's own doc comment). Only meaningful for chain
    # modules whose scrape() accepts a `deadline` kwarg; the other, fast
    # chains ignore it.
    deadline_seconds = os.environ.get("SCRAPE_DEADLINE_SECONDS")
    deadline = time.time() + int(deadline_seconds) if deadline_seconds else None

    for chain in chains:
        print(f"=== {chain} ===")
        started = time.time()
        try:
            mod = importlib.import_module(chain)
            if "deadline" in inspect.signature(mod.scrape).parameters:
                rows = mod.scrape(limit, deadline=deadline)
            else:
                rows = mod.scrape(limit)
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            summary[chain] = {"error": f"{type(e).__name__}: {e}"}
            continue

        out = os.path.join(ROOT, "data", "latest", f"{chain}.jsonl")
        # persist continuation offset if the time budget stopped us mid-chain
        import common as _c
        cont = getattr(_c, "last_continue_offset", None)
        state_path = os.path.join(ROOT, "data", "latest", "scrape_offsets.json")
        offsets = {}
        if os.path.exists(state_path):
            try:
                offsets = json.load(open(state_path))
            except json.JSONDecodeError:
                offsets = {}
        if cont:
            offsets[chain] = {"offset": cont, "date": today}
        else:
            offsets.pop(chain, None)
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        json.dump(offsets, open(state_path, "w"), indent=1)

        # Per-chain signals only, never the blanket workflow-level RESUME
        # env var (`-f resume=true` on the WHOLE dispatch). Confirmed live
        # (2026-09-18): continue-check sets that flag whenever ANY chain is
        # incomplete, which - given the completion-marker bug just fixed
        # below - has been true almost constantly for weeks. Gating the
        # collapse guard's bypass on that blanket flag meant it was
        # effectively disabled for every chain, every time, during nearly
        # every run, including chains that scraped a completely normal
        # pass that day - a genuinely broken scrape (a site outage, a
        # parser regression) could have slipped through undetected the
        # entire time, for the very case the guard exists to catch. A
        # chain only needs its OWN guard bypassed when ITS OWN scrape
        # is legitimately still catching up.
        checkpoint_pending = (
            os.path.exists(os.path.join(ROOT, "data", "latest", f".seen-{chain}.txt"))
            or os.path.exists(os.path.join(ROOT, "data", "latest", f".checkpoint-{chain}.jsonl"))
        )
        resuming = bool(cont) or checkpoint_pending
        # Read the existing file keyed by sku/url, same key the merge below
        # uses - prev_count is the DEDUPED count, not raw line count. A file
        # bloated by an old bug (confirmed live: bauhaus/davidsen/fog/power/
        # haraldnyborg all sat at 5x their real size) makes every correct,
        # normally-sized fresh scrape look like a "collapse" against the
        # raw line count, so the guard rejected every good run since - kept
        # re-committing the same bloat forever and never once let a real,
        # accurate scrape through. Deduping first means the guard compares
        # against what the catalog actually contains.
        existing = {}
        if os.path.exists(out):
            with open(out, encoding="utf-8") as f:
                for line in f:
                    try:
                        rr = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    existing[rr.get("sku") or rr.get("url")] = rr
        prev_count = len(existing)
        if not resuming and prev_count and len(rows) < prev_count * 0.3:
            summary[chain] = {
                "error": f"collapse guard: {len(rows)} rows vs {prev_count} before",
                "kept_previous": True,
            }
            print(f"  !! kept previous snapshot ({len(rows)} new vs {prev_count})")
            continue

        from common import write_jsonl
        # merge with previous file, keeping the LATEST observation per key —
        # files stay catalog-sized no matter how many partial passes feed them
        fresh_keys = set()
        for r in rows:
            existing[r.get("sku") or r.get("url")] = r
            fresh_keys.add(r.get("sku") or r.get("url"))
        expired = 0
        if not limit and not resuming and rows and chain not in ROTATING_CHAINS:
            stamped, expired, skipped = expire_missing(existing, fresh_keys, today)
            if skipped:
                print(f"  expiry skipped: {skipped}")
            elif stamped or expired:
                print(f"  {stamped} products newly missing, {expired} expired (missing >= {EXPIRE_AFTER_DAYS} days)")
        merged_rows = list(existing.values())
        write_jsonl(out, merged_rows)
        # completion marker only when every url in the chain was processed.
        #
        # Confirmed live (2026-09-18): this used to gate on the WORKFLOW-
        # level `RESUME` env var (`-f resume=true` on the whole dispatch),
        # not anything specific to this chain. The very first time
        # continue-check ever redispatched with resume=true, EVERY chain's
        # marker stopped updating - including chains that scraped a
        # completely normal, full, successful pass that same run - because
        # the blanket flag suppressed `complete_now` for all nine
        # regardless. With no chain ever reaching "complete" again, every
        # future check_incomplete.py run saw the same stale (weeks-old)
        # markers, endlessly triggered another resume=true redispatch, and
        # the pipeline never went idle - found via a live chain of 5+
        # back-to-back full runs with zero gap, which is also what was
        # actually delaying the nightly cron (not GitHub's top-of-hour
        # queueing, the earlier diagnosis - the concurrency slot was just
        # never free).
        #
        # Fixed by checking what actually happened to THIS chain's own
        # scrape instead: `resuming` (computed above, same `cont` +
        # checkpoint-file signals the guard bypass just used) - `cont` is
        # scrape_urls' own per-chain signal that ITS time budget cut it
        # short (the 6 non-checkpoint chains); leftover checkpoint/seen
        # files are scrape_with_checkpoint's own signal of the same thing
        # (silvan/xlbyg/stark, and for stark specifically that's scoped to
        # today's rotation slice, which is the right, achievable
        # definition of "done for today" - the separate row-count-vs-
        # EXPECTED check in check_incomplete.py is what judges whether the
        # accumulated catalog is big enough).
        complete_now = not limit and not resuming and len(rows) > 0
        marker = os.path.join(ROOT, "data", "latest", f".{chain}-complete")
        if complete_now:
            # Stamped with the date the scrape FINISHED, not `today`
            # (computed once at process start): a run that started before
            # 00:00 UTC and finished after would otherwise write yesterday's
            # date, which check_incomplete.py (comparing against the date it
            # runs on) reads as "not done today" - forcing a needless full
            # re-scrape of a chain that had just completed.
            with open(marker, "w") as mf:
                mf.write(date.today().isoformat())
        elif os.path.exists(marker):
            os.remove(marker)
        print(f"  {len(rows)} fresh rows ({len(merged_rows)} total after merge, "
              f"{max(0, prev_count - len(fresh_keys))} prior retained)")

        prev = load_prev(chain)
        changes, suspicious = [], 0
        for r in rows:
            key = r.get("sku") or r.get("url")
            old = prev.get(key)
            if old and old.get("price") != r.get("price"):
                old_p, new_p = old.get("price") or 0, r.get("price") or 0
                ratio = (new_p / old_p) if old_p else 999
                # >8x jump in one day is almost always a parse error, not a price
                flag = {"suspicious": True} if ratio > 8 or ratio < 0.125 else {}
                if flag:
                    suspicious += 1
                changes.append(dict({"key": key, "old_price": old.get("price"),
                                "new_price": r.get("price"),
                                "date": today, "url": r.get("url")}, **flag))
        if changes:
            hdir = os.path.join(ROOT, "data", "history", chain)
            os.makedirs(hdir, exist_ok=True)
            hpath = os.path.join(hdir, f"{today}.jsonl")
            mode = "a" if os.path.exists(hpath) else "w"
            with open(hpath, mode, encoding="utf-8") as f:
                for c in changes:
                    f.write(json.dumps(c, ensure_ascii=False) + "\n")

        summary[chain] = {
            "products": len(rows),
            "price_changes": len(changes),
            "suspicious_changes": suspicious,
            "expired": expired,
            "seconds": round(time.time() - started, 1),
        }
        print(f"  {len(rows)} products, {len(changes)} price changes")

    if only:
        spath = os.path.join(ROOT, "data", "latest", f"summary-{only}.json")
        json.dump({"date": today, "chains": summary}, open(spath, "w"), indent=1)
    else:
        merged = os.path.join(ROOT, "data", "latest", "prices.jsonl")
        n = 0
        with open(merged, "w", encoding="utf-8") as out:
            for chain in CHAINS:
                p = os.path.join(ROOT, "data", "latest", f"{chain}.jsonl")
                if not os.path.exists(p):
                    continue
                with open(p, encoding="utf-8") as f:
                    for line in f:
                        out.write(line)
                        n += 1
        json.dump({"date": today, "total_rows": n, "chains": summary},
                  open(os.path.join(ROOT, "data", "latest", "summary.json"), "w"),
                  indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
