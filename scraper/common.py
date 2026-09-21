"""DK Byggepriser — nightly price snapshots from Danish building-supply chains.

10 chains, all public retail prices, no logins. Sources verified 2026-08-28.

Output:
  data/latest/<chain>.jsonl          full snapshot (overwritten each run)
  data/latest/prices.jsonl           merged all chains (what the API reads)
  data/history/<chain>/<date>.jsonl  only price CHANGES vs previous day
"""
import re
import os
import time
import random
import json
import gzip
import urllib.request
import urllib.parse
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")
TIMEOUT = 25
WORKERS = int(os.environ.get("SCRAPE_WORKERS", "24"))

_last_req = {}
_inflight = {}
import threading
_lock = threading.Lock()
# Per-host lane control: up to 3 concurrent connections, >=0.45s between
# request starts. ~2.2 req/s/host max — comparable to an active shopper,
# 3x faster than the old single-lane throttle (which made full-catalog
# runs exceed CI time limits).
MAX_LANES = int(os.environ.get("SCRAPE_LANES", "3"))
MIN_GAP = float(os.environ.get("SCRAPE_GAP", "0.45"))

# Per-host adaptive backoff - confirmed live (skousen, 2026-09-16): a site
# rate-limiting us gets one 429/503/403 per worker thread, and each thread
# independently sleeps a flat 45-75s then retries at the SAME per-host rate
# it was already using - up to MAX_LANES threads all retrying a struggling
# site at once isn't backing off, it's re-hammering it on a timer. This
# makes the whole host pause (not just the one URL that got blocked) once
# any thread sees a block signal, escalating on repeated blocks instead of
# retrying at an unchanged pace - standard adaptive-backoff practice, not a
# judgment call about how aggressive to be with any one site.
_host_backoff_until = {}
BACKOFF_INITIAL = 60.0
BACKOFF_MAX = 600.0


def _note_rate_limited(host):
    with _lock:
        now = time.time()
        prev_until = _host_backoff_until.get(host, 0)
        if prev_until > now:
            # still within a previous backoff window and got blocked again -
            # escalate rather than restart the same short wait
            duration = min(BACKOFF_MAX, (prev_until - now) * 2)
        else:
            duration = BACKOFF_INITIAL
        _host_backoff_until[host] = now + duration


def _throttle(host):
    while True:
        with _lock:
            now = time.time()
            if now < _host_backoff_until.get(host, 0):
                pass  # host is in a backoff window - wait it out below
            elif _inflight.get(host, 0) < MAX_LANES and \
                    now - _last_req.get(host, 0) >= MIN_GAP:
                _last_req[host] = now
                _inflight[host] = _inflight.get(host, 0) + 1
                return
        time.sleep(0.05)


def _release(host):
    with _lock:
        _inflight[host] = max(0, _inflight.get(host, 1) - 1)


import urllib.parse

def _encode_url(url):
    """URL-encode non-ASCII characters (Norwegian ø, Swedish å, etc.)."""
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/%:+@")
    query = urllib.parse.quote(parts.query, safe="=&%?/:+@")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def get(url, binary=False, max_bytes=40000000):
    """Polite GET: per-host lane throttle + jitter, realistic UA."""
    url = _encode_url(url)
    host = re.match(r"https?://([^/]+)", url).group(1)
    _throttle(host)
    try:
        return _get_inner(url, binary, max_bytes, host)
    finally:
        _release(host)


def _get_inner(url, binary, max_bytes, host):
    last_err = None
    data = None
    for attempt in range(3):
        try:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None  # manual redirect handling

            opener = urllib.request.build_opener(NoRedirect)
            cur = url
            for _ in range(5):
                req = urllib.request.Request(cur, headers={"User-Agent": UA, "Accept": "*/*"})
                try:
                    with opener.open(req, timeout=TIMEOUT) as r:
                        data = r.read(max_bytes)
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                        cur = urllib.parse.urljoin(cur, e.headers["Location"])
                        continue
                    raise
            if data is None:
                raise RuntimeError("redirect loop: " + url)
            if urllib.parse.urlsplit(cur).path.rstrip("/") != urllib.parse.urlsplit(url).path.rstrip("/"):
                # a "product" URL that lands elsewhere = wrong product data
                raise ValueError(f"redirected: {url} -> {cur}")
            last_err = None
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise  # dead URL — retrying is pointless
            last_err = e
            if e.code in (429, 503, 403):
                _note_rate_limited(host)  # pause every worker on this host, not just this URL
                time.sleep(45 + random.random() * 30)  # this worker's own WAF cooldown
            else:
                time.sleep(1.5 * (attempt + 1) + random.random())
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1) + random.random())
    if last_err is not None:
        raise last_err
    if url.endswith(".gz") and not binary:
        data = gzip.decompress(data)
    return data if binary else data.decode("utf-8", errors="replace")


def get_json(url):
    return json.loads(get(url))


def pmap(fn, items, workers=None):
    """Threaded map that preserves order and never raises."""
    rows = []
    with ThreadPoolExecutor(max_workers=workers or WORKERS) as ex:
        for r in ex.map(fn, items):
            rows.extend(r or [])
    return rows


def sitemap_urls(xml):
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)


LD_RE = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def _iter_products(obj):
    """Yield Product/ProductGroup dicts from parsed ld+json (incl @graph)."""
    if isinstance(obj, dict):
        if obj.get("@type") in ("Product", "ProductGroup"):
            yield obj
        for v in obj.values():
            yield from _iter_products(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from _iter_products(it)


def ldjson_products(html):
    out = []
    for m in LD_RE.findall(html):
        try:
            d = json.loads(m)
        except json.JSONDecodeError:
            continue
        out.extend(_iter_products(d))
    return out


def offer_from_ld(product):
    off = product.get("offers") or {}
    if isinstance(off, list):
        off = off[0] if off and isinstance(off[0], dict) else {}
    price = off.get("price")
    if price in (None, "", 0):
        return None
    avail = str(off.get("availability") or "")
    in_stock = ("InStock" in avail) if avail else None  # absent = unknown
    return {
        "price": float(price),
        "currency": off.get("priceCurrency", "DKK"),
        "in_stock": in_stock,
    }


def parse_dk_price(s):
    """'5.590,00' -> 5590.0 ; '49.95' -> 49.95 ; None if unparseable."""
    if not s:
        return None
    s = s.strip().replace("kr", "").replace(" ", "").replace("\xa0", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


_deadline = None


def scrape_urls(urls, handle):
    """Parallel scrape with TIME BUDGET + resume.

    SCRAPE_OFFSET: skip first N urls (continuing a previous partial run).
    SCRAPE_BUDGET: stop fetching after this many minutes, reporting the
    offset to continue from — the orchestrator commits it as state so the
    next run continues where this one stopped. Big chains therefore finish
    across 2-3 runs instead of dying at the CI limit every night.
    """
    global _deadline
    off = int(os.environ.get("SCRAPE_OFFSET", "0"))
    budget = os.environ.get("SCRAPE_BUDGET")
    if budget:
        _deadline = time.time() + float(budget) * 60
    if off:
        urls = urls[off:]
    def work(u):
        try:
            return handle(u, get(u)) or []
        except Exception as e:
            print(f"  ! {u}: {e}")
            return []
    rows = []
    done = 0
    def tracked(u):
        nonlocal done
        if _deadline and time.time() > _deadline:
            return None  # budget exhausted: stop issuing new fetches
        r = work(u)
        done += 1
        return r
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(tracked, urls):
            if r is None:
                break
            rows.extend(r or [])
    processed = off + min(done, len(urls))
    if _deadline and done < len(urls):
        remaining = len(urls) - done
        globals()["last_continue_offset"] = processed
        print(f"  TIME_BUDGET_REACHED offset={processed} remaining={remaining}")
    return rows


def scrape_with_checkpoint(chain, urls, handle, limit=None, deadline=None, fetch_max_bytes=None):
    """For catalogs too large for one CI job to finish (Silvan ~41k URLs,
    XL-BYG ~35k+ across 7 sub-sitemaps, Stark 100k+ variant URLs, many dead)
    - every nightly run for these three has been getting killed by CI's own
    timeout partway through, every single day, since this project started.
    Plain scrape_urls()/pmap() can't survive that: results only exist in a
    Python list held in memory, and CI's timeout SIGKILLs the process with
    no chance to run any cleanup code, so 100% of an interrupted run's work
    was lost - the "resume" the workflow re-dispatches for restarts from
    URL #1 every time, re-scraping (and duplicating, since nothing
    de-duplicated on append) the same first few hundred URLs and never
    making net progress. This instead:

    1. Writes each URL's outcome to data/latest/.seen-<chain>.txt and each
       resulting row to data/latest/.checkpoint-<chain>.jsonl AS IT GOES
       (flushed per URL), not at the end - however far a run gets before
       being killed is durably on disk already.
    2. On the NEXT invocation (today's next continue-check retry, or
       literally the same cron slot tomorrow if the catalog is bigger than
       one day's realistic throughput at the deliberately polite request
       rate), reads that seen-set back and skips every URL already
       attempted - real forward progress instead of restarting.
    3. Returns the full CUMULATIVE checkpoint (de-duplicated by url/sku) -
       everything attempted across however many invocations it took so
       far, not just this one's slice - so the per-chain output file gets
       progressively MORE complete every time this runs, rather than an
       all-or-nothing wait for one invocation to somehow get through a
       100k-URL list. Once the full list is actually covered, the
       seen-set/checkpoint reset so tomorrow starts a clean pass against
       that day's re-fetched sitemap (real catalog changes still show up).

    Only engages when `limit` is falsy - an explicit smoke-test slice skips
    all of this and behaves exactly like plain scrape_urls, so a deliberate
    small test run can never be confused with (or pollute) real daily
    progress.

    `deadline` (a `time.time()`-style unix timestamp) matters because the
    per-URL checkpoint files above only protect a run that gets to keep
    running - CI's own job timeout SIGKILLs the whole job the instant it's
    hit, which tears down the runner (and every byte of "durable" progress
    on its local disk) before the caller's own commit-and-push step ever
    gets to run. Confirmed live: silvan/xlbyg/stark have never once
    finished OR made committed progress since this function shipped,
    because every run that didn't finish naturally was a run that
    contributed nothing at all. Stopping a comfortable margin BEFORE that
    external kill - by giving up on any URL not yet complete and returning
    whatever's checkpointed instead of waiting on `ex.map` to visit every
    one - means the calling script exits normally, the checkpoint files
    make it into the same commit as the day's `.jsonl` output, and the
    *next* invocation actually resumes into new URLs instead of into an
    empty seen-set again.
    """
    if limit:
        return scrape_urls(urls[:limit], handle)

    seen_path = f"data/latest/.seen-{chain}.txt"
    checkpoint_path = f"data/latest/.checkpoint-{chain}.jsonl"
    os.makedirs(os.path.dirname(seen_path), exist_ok=True)

    seen = set()
    if os.path.exists(seen_path):
        with open(seen_path, encoding="utf-8") as f:
            seen = {line.rstrip("\n") for line in f if line.strip()}

    remaining = [u for u in urls if u not in seen]
    if seen:
        print(f"  resume: {len(seen)} already attempted today, {len(remaining)} left of {len(urls)}")

    if remaining:
        def work(u):
            # Returns (url, rows) - or (url, None) for a TRANSIENT fetch
            # failure (429/403/5xx/timeout/connection error). Confirmed
            # live (2026-09-18, skousen: 84 x HTTP 429): every exception
            # used to become (u, []) and the url was then written to the
            # seen-set, i.e. "handled for today" - so a product that only
            # hit a rate-limit burst was silently never re-tried and just
            # kept yesterday's price via the merge. Only a permanent
            # outcome (404, "redirected" to another product) or a parse
            # problem may legitimately count as done.
            def fetch(max_bytes=None):
                try:
                    return get(u, max_bytes=max_bytes) if max_bytes else get(u), True
                except urllib.error.HTTPError as e:
                    print(f"  ! {u}: {e}")
                    return None, e.code in (404, 410)   # (no body, permanent?)
                except ValueError as e:      # "redirected: ..." = dead/moved URL
                    print(f"  ! {u}: {e}")
                    return None, True
                except Exception as e:
                    print(f"  ! {u}: {e}")
                    return None, False

            # fetch_max_bytes: read only the head of the page (skousen's
            # product data sits in the first ~140KB of 500-900KB pages).
            # If the head yields no row, fall back to the full page before
            # concluding there's no product, so an unusual layout can't
            # silently lose rows.
            html, ok = fetch(fetch_max_bytes)
            if html is None:
                return u, ([] if ok else None)
            try:
                rows = handle(u, html) or []
                if not rows and fetch_max_bytes:
                    html, ok = fetch()
                    if html is None:
                        return u, ([] if ok else None)
                    rows = handle(u, html) or []
                return u, rows
            except Exception as e:
                print(f"  ! {u}: parse error {type(e).__name__}: {e}")
                return u, []

        with open(seen_path, "a", encoding="utf-8") as seen_f, \
                open(checkpoint_path, "a", encoding="utf-8") as ckpt_f:

            def record(u, rows):
                seen_f.write(u + "\n")
                seen_f.flush()
                for row in rows:
                    ckpt_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                if rows:
                    ckpt_f.flush()

            def run_pass(todo, workers):
                """Scrape `todo`; returns (transient-failed urls, hit_deadline).
                Successful/permanent outcomes are recorded immediately."""
                failed, hit = [], False
                ex = ThreadPoolExecutor(max_workers=workers)
                try:
                    futures = [ex.submit(work, u) for u in todo]
                    for fut in as_completed(futures):
                        u, rows = fut.result()
                        if rows is None:
                            failed.append(u)   # NOT marked seen (see work())
                        else:
                            record(u, rows)
                        if deadline and time.time() > deadline:
                            # `cancel_futures=True` below drops every
                            # not-yet-started future at once; only the few
                            # already mid-request run on to their own
                            # timeout - a small bounded tail.
                            hit = True
                            break
                finally:
                    ex.shutdown(wait=False, cancel_futures=True)
                return failed, hit

            failed, hit_deadline = run_pass(remaining, WORKERS)
            if failed and not hit_deadline:
                # One bounded retry for transient failures (rate-limit
                # bursts etc.) after letting the host cool off. Whatever
                # still fails is recorded as attempted so a genuinely
                # broken URL can't keep the chain "resuming" forever.
                print(f"  {chain}: retrying {len(failed)} transient failures once")
                time.sleep(min(120, 30 + len(failed) * 0.2))
                failed2, hit_deadline = run_pass(failed, min(WORKERS, MAX_LANES))
                if not hit_deadline:
                    for u in failed2:
                        record(u, [])
                    if failed2:
                        print(f"  {chain}: {len(failed2)} urls still failing after retry - keeping prior data")
            if hit_deadline:
                print(f"  {chain}: soft deadline reached, stopping early "
                      f"(transient failures left unseen for the next run)")
        with open(seen_path, encoding="utf-8") as f:
            seen = {line.rstrip("\n") for line in f if line.strip()}

    cumulative, dedup_keys = [], set()
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = row.get("url") or row.get("sku")
                if key in dedup_keys:
                    continue
                dedup_keys.add(key)
                cumulative.append(row)

    if len(seen) >= len(urls):
        print(f"  {chain}: full catalog covered today ({len(cumulative)} rows) - resetting checkpoint for tomorrow")
        for p in (seen_path, checkpoint_path):
            if os.path.exists(p):
                os.remove(p)
    else:
        print(f"  {chain}: {len(seen)}/{len(urls)} urls covered so far today, {len(cumulative)} rows checkpointed")

    return cumulative


def rotate_slice(urls, rotation_days, today_epoch_day=None):
    """Deterministic 1/rotation_days slice of `urls`, cycling by day-of-epoch
    so the full list is covered once every `rotation_days` days.

    Exists for chains whose real catalog (post dead-URL filtering) is too
    large to fetch in one CI job's time budget no matter how politely rate-
    limited (stark: ~85k sitemap URLs, most of them dead - even at ~2.2
    req/s that's ~10+ hours). The two "smarter" alternatives were checked
    live against real sitemaps/product pages first: sitemap `<lastmod>` is
    a single build-timestamp shared by EVERY url in the file (confirmed on
    both silvan's and stark's real sitemaps - all 50,000 stark entries
    carried the identical value), and none of these sites' product pages
    return a real ETag/Last-Modified either (all no-cache/no-store,
    server-rendered). Neither gives a trustworthy "did this specific
    product change" signal - trusting either risks silently never
    refreshing a chain again if a site's stamp ever freezes, which is
    exactly the class of bug this whole pipeline has been getting fixed
    for. This makes no claim about what changed: it just guarantees every
    url gets refetched at least once every `rotation_days` days, on our
    own schedule, with no external signal to get wrong. The tradeoff is
    explicit and bounded (a given product can be up to rotation_days-1
    days stale) rather than an unbounded, silent risk.

    Pure and stateless by design - the same day always maps to the same
    slice, so a same-day retry/resume sees identical input without needing
    its own persisted state.
    """
    if today_epoch_day is None:
        today_epoch_day = int(time.time() // 86400)
    ordered = sorted(urls)
    nth = today_epoch_day % rotation_days
    return [u for i, u in enumerate(ordered) if i % rotation_days == nth]


def write_jsonl(path, rows):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


MIN_PRICE, MAX_PRICE = 0.5, 250000.0  # DKK sanity bounds


def sane_price(p):
    """Reject zeros, negatives and absurd values that signal parse errors."""
    try:
        p = float(p)
    except (TypeError, ValueError):
        return None
    return p if MIN_PRICE <= p <= MAX_PRICE else None


def valid_ean(e):
    """GTIN-8/12/13/14 checksum validation — drops retailer junk GTINs.
    Weights run 3,1,3,1... from the rightmost DATA digit (check digit excluded)."""
    if e is None:
        return None
    s = str(e).strip()
    if not s.isdigit() or len(s) not in (8, 12, 13, 14):
        return None
    digits = [int(c) for c in s]
    check = digits.pop()
    total = sum(d * (3 if i % 2 == 0 else 1)
                for i, d in enumerate(reversed(digits)))
    return s if (10 - total % 10) % 10 == check else None


def first_str(v):
    """ld+json 'image' can be str, list or nested — normalize to first URL."""
    if isinstance(v, str):
        return v or None
    if isinstance(v, list):
        for it in v:
            if isinstance(it, str) and it:
                return it
            if isinstance(it, dict) and it.get('url'):
                return it['url']
    if isinstance(v, dict):
        return v.get('url')
    return None


HTML_GTIN_RE = re.compile(r'"(?:gtin(?:13)?|ean)"\s*:\s*"(\d{8,14})"')


def html_gtin(html):
    """Fallback: many chains embed gtin in a JSON state blob outside ld+json.
    Returns first checksum-valid GTIN on the page."""
    for m in HTML_GTIN_RE.finditer(html):
        v = valid_ean(m.group(1))
        if v:
            return v
    return None
