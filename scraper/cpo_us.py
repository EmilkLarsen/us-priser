"""CPO Outlets (USD, US — power tools + job-site supplies; Salesforce Commerce
Cloud). Replaces the Cloudflare-walled ace_us (acehardware.com serves a "Just
a moment..." JS challenge even from residential IPs — verified 2026-09-26;
its sitemaps list 157 product batches but product pages are unfetchable).

sitemap_index.xml -> sitemap_{0,1,...}.xml, 5,000 URLs each (verified 2026-09-26).
Product URLs: https://.../<slug>/<pid>.html — pid like "dfon50".

Product pages (SFCC, verified): display price
'class="value salesprice minisalesprice1">$9.49' (sale; the "stdprice value"
class is the struck-through was-price — parse salesprice only), SKU from
data-pid, title from <title>, image from og:image. No EAN/GTIN in markup.
"""
import re
from common import get, sane_price, write_jsonl, scrape_urls

BASE = "https://www.cpooutlets.com"
OUT = "data/latest/cpo_us.jsonl"


def fetch_url_list(limit=None):
    idx = get(f"{BASE}/sitemap_index.xml")
    files = [m for m in re.findall(r"<loc>([^<]+)</loc>", idx)
             if re.search(r"/sitemap_\d+\.xml$", m)]
    urls = []
    for f in files:
        xml = get(f)
        urls.extend(u.strip() for u in re.findall(r"<loc>([^<]+)</loc>", xml)
                    if u.strip().endswith(".html"))
        if limit and len(urls) >= limit:
            break
    return urls[:limit] if limit else urls


def handle(u, html):
    pid = re.search(r"/([a-z0-9_-]+)\.html?$", u)
    p = None
    m = re.search(r'class="value salesprice[^"]*">\s*\$([0-9,]+(?:\.[0-9]{2})?)',
                  html)
    if m:
        p = sane_price(float(m.group(1).replace(",", "")))
    else:
        # fallback: the view_item dataLayer JSON (item_id must equal the URL
        # pid — other price tokens on the page are recommendations/carousels)
        m2 = re.search(r'"event"\s*:\s*"view_item".{0,500}?"item_id"\s*:\s*'
                       r'"([^"]+)".{0,500}?"price"\s*:\s*([0-9.]+)', html, re.S)
        if m2 and (not pid or m2.group(1) == pid.group(1)):
            p = sane_price(float(m2.group(2)))
    if not p:
        return []
    img = re.search(r'property="og:image"\s+content="([^"]+)"', html)
    t = re.search(r"<title[^>]*>([^<]+)</title>", html)
    name = (t.group(1).strip() if t else u.rsplit("/", 1)[-1])
    return [{
        "chain": "cpo_us",
        "country": "us",
        "currency": "USD",
        "sku": pid.group(1) if pid else None,
        "ean": None,
        "name": name,
        "url": u,
        "price": p,
        "in_stock": None,
        "image": img.group(1).strip() if img else None,
    }]


def scrape(limit=None):
    return scrape_urls(fetch_url_list(limit), handle)


if __name__ == "__main__":
    import sys
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    rows = scrape(lim)
    write_jsonl(OUT, rows)
    print("cpo_us: %d products -> %s" % (len(rows), OUT))
