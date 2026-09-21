"""AceHardware.com (USD, USA) — productBatch sitemaps; product URLs end /<id>;
clean ld+json Product with priceSpecification.price + gtin13 + availability."""
import re
from common import get, sitemap_urls, ldjson_products, offer_from_ld, sane_price, valid_ean, first_str, write_jsonl, pmap

BASE = "https://www.acehardware.com"
OUT = "data/latest/ace_us.jsonl"


def fetch_url_list(limit=None):
    idx = get(f"{BASE}/sitemap.xml")
    files = sitemap_urls(idx)
    urls = []
    for f in files:
        if "/productBatch/" not in f:
            continue
        us = [u for u in sitemap_urls(get(f))
              if re.search(r"/departments/.+/\d+$", u)]
        urls.extend(us)
        if limit and len(urls) >= limit:
            break
    return urls[:limit] if limit else urls


def handle(u, html):
    rows = []
    for p in ldjson_products(html):
        off = p.get("offers") or {}
        if isinstance(off, list):
            off = off[0] if off and isinstance(off[0], dict) else {}
        amt = off.get("price")
        cur = off.get("priceCurrency", "USD")
        if not amt:
            ps = off.get("priceSpecification") or []
            if isinstance(ps, list) and ps and ps[0].get("price"):
                amt = ps[0]["price"]
                cur = ps[0].get("priceCurrency", "USD")
            else:
                continue
        price = sane_price(amt)
        if not price:
            continue
        avail = str(off.get("availability") or "")
        sku = u.rstrip("/").rsplit("/", 1)[-1]
        rows.append({
            "chain": "ace_us",
            "country": "us",
            "currency": cur,
            "sku": sku,
            "ean": valid_ean(p.get("gtin13") or p.get("gtin") or p.get("ean")),
            "name": p.get("name"),
            "url": u,
            "price": price,
            "in_stock": ("InStock" in avail) if avail else None,
            "image": first_str(p.get("image")),
        })
        break
    return rows


def scrape(limit=None):
    def work(u):
        try:
            return handle(u, get(u))
        except Exception as e:
            print(f"  ! {u}: {e}")
            return []
    return pmap(work, fetch_url_list(limit))


if __name__ == "__main__":
    import sys
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    rows = scrape(lim)
    write_jsonl(OUT, rows)
    print("ace_us: %d products -> %s" % (len(rows), OUT))
