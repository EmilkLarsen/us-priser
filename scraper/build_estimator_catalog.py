#!/usr/bin/env python3
"""Build data/latest/estimator_catalog.json — the small feed the Fixer app
fetches at runtime (MaterialCatalogStore.remoteCatalogURL).

For each of the ~707 canonical material keys the app knows how to match an AI
material list against (scraper/estimator_keys.json, mirrored from the app's
material_catalog_v1.json), this finds the best real matching products in
prices.jsonl and attaches them WITH their parsed pack size. The app hands
those to the estimate AI, which picks a product, works out how much is needed
from the roof area, rounds up to whole packs, and sums the real line costs.

No synthetic/median price and no hand-tuned fallback price is emitted — the
app is moving to live retail prices only. Keys with no confident product
match are still emitted (so the app keeps the taxonomy) but carry no
products, and the estimate is told to flag those lines as unverified.

Output: bare JSON array, one entry per key:
  {key, name, synonyms, unit,
   products?: [{t: title, p: price, c: chain, u: url, pack?: {q: float, u: unit}}],
   updated?: YYYY-MM-DD}
~400 KB (well under 100 KB gzipped over the CDN).
"""
import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST = os.path.join(ROOT, "data", "latest")
HERE = os.path.dirname(os.path.abspath(__file__))

MAX_PRODUCTS_PER_KEY = 6
MAX_PRICE = 15000          # a single material line item is never this expensive
MIN_PRICE = 3
# Titles containing these are finished structures / signage / kits, not the
# raw material — they poison a "cheapest match" pick.
JUNK = re.compile(
    r"\b(skur|hytte|shelter|b[aå]lhytte|cykelskur|legehus|pavillon|carport|"
    r"drivhus|skilt|klisterm[aæ]rke|pickup|bog|dvd|gavekort|stiga|"
    r"n[aå]lefilt|t[oø]jklemme|legetoej|leget[oø]j)\b", re.I)

# Accessory / fixing / consumable words. When a product title's HEAD noun is one
# of these, it's almost always the wrong row for a material line ("undertagsclips"
# for "undertag", "tagpapklæber" for "tagpap"). Applied globally, in norm() space.
ACCESSORY = {
    "clips", "klips", "beslag", "krog", "kroge", "skrue", "skruer", "soem",
    "klammer", "haefteklammer", "plugs", "dyvel", "strammer", "strips", "spaendebaand",
    "klaeber", "lim", "primer", "tape", "fuge", "fugemasse", "silikone", "manchet",
    "krave", "hjoerne", "prop", "haette", "haet", "rist", "filter", "net",
    "maling", "rens", "algefjerner", "impraegnering", "gennemfoering", "adapter",
    "kobling", "muffe", "endebund", "samlestykke", "udloeb", "boejning", "vinkel",
    "holder", "baerer", "konsol", "montagesaet", "reparation", "reparationskit",
}

# Sane per-catalog-unit price band. A product whose derived per-unit price lands
# outside this is a unit mismatch / wrong variant and is dropped.
SANE_UNIT_BAND = {
    "m2": (5, 900),      # covering, boards, membrane, insulation
    "m": (3, 400),       # battens, gutters, fascia, flashing
    "roll": (40, 3500),
    "bag": (20, 800),
    "box": (25, 1200),
    "set": (30, 4000),
    "liter": (15, 600),
    "kg": (2, 200),
    "pcs": (1, 3000),
}


def norm(s: str) -> str:
    s = (s or "").lower()
    # Danish letters don't NFKD-decompose — transliterate before the ascii strip
    # so "klæber"/"nedløb"/"lægte" survive as klaeber/nedloeb/laegte.
    s = s.translate(str.maketrans({"æ": "ae", "ø": "oe", "å": "aa",
                                   "ä": "ae", "ö": "oe", "ü": "ue"}))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_pack(name: str):
    """Best-effort pack size from a retail title. Returns {"q": float, "u": unit}
    or None. unit is one of m2, m, pcs, l, kg."""
    s = (name or "").lower().replace(",", ".")
    # area roll: "1,1x50 m", "0,25 X 10,0 m", "2,15x46,5 m"
    m = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*m(?:\b|eter)", s)
    if m:
        a = float(m.group(1)) * float(m.group(2))
        if 0.5 <= a <= 200:
            return {"q": round(a, 1), "u": "m2"}
    # explicit m2 / kvm
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m2|m²|kvm)\b", s)
    if m:
        return {"q": float(m.group(1)), "u": "m2"}
    # count: "100 stk", "50 stk.", "a 35mm pakket" -> ignore; "20 stk"
    m = re.search(r"(\d+)\s*stk\b", s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 5000:
            return {"q": float(n), "u": "pcs"}
    # timber / batten length: "38x73 ... 420 cm", "... 4200 mm", "600cm"
    m = re.search(r"(\d{2,4})\s*cm\b", s)
    if m:
        v = int(m.group(1)) / 100
        if 1 <= v <= 12:
            return {"q": round(v, 1), "u": "m"}
    m = re.search(r"\b(\d{3,5})\s*mm\b", s)
    if m:
        v = int(m.group(1)) / 1000
        if 1 <= v <= 12:
            return {"q": round(v, 1), "u": "m"}
    # linear metres: "x 5 m", "x 80m", "310 mm x 5 m", "str 11 600cm" handled above
    m = re.search(r"[x×]\s*(\d+(?:\.\d+)?)\s*m\b", s)
    if m:
        v = float(m.group(1))
        if 1 <= v <= 100:
            return {"q": v, "u": "m"}
    # volume / weight
    m = re.search(r"(\d+(?:\.\d+)?)\s*(l|liter|ltr)\b", s)
    if m:
        return {"q": float(m.group(1)), "u": "l"}
    m = re.search(r"(\d+(?:\.\d+)?)\s*kg\b", s)
    if m:
        return {"q": float(m.group(1)), "u": "kg"}
    return None


def load_products():
    prods = []
    with open(os.path.join(LATEST, "prices.jsonl"), encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            p = r.get("price")
            name = r.get("name", "")
            if not isinstance(p, (int, float)) or not (MIN_PRICE <= p <= MAX_PRICE):
                continue
            if JUNK.search(name):
                continue
            r["_norm"] = norm(name)
            prods.append(r)
    return prods


_PAREN = re.compile(r"\(.*?\)")
_UNITWORD = re.compile(r"\b(rulle|rull|pcs|stk|kit|set|box|kasse|pk|pakke)\b")

STOP = {"til", "og", "med", "for", "inkl", "pr", "stk", "mm", "cm", "m", "m2",
        "sort", "hvid", "graa", "roed", "bla", "gr", "a", "ce", "kg", "l",
        "70", "c18", "type"}


def _content_tokens(s):
    return [t for t in norm(s).split() if t not in STOP and len(t) > 1]


def key_phrases(item):
    """Match phrases for a key: the canonical name (parentheticals + unit words
    stripped) plus each synonym, longest first."""
    base = _UNITWORD.sub(" ", _PAREN.sub(" ", item["name"]))
    raw = {norm(base)} | {norm(s) for s in item.get("synonyms", [])}
    return sorted((p for p in raw if len(p) >= 3),
                  key=lambda p: -len(p.split()))


def match_products(item, prods):
    """A product matches when every token of some match phrase is a substring of
    its normalised title. Score = word-count of the most specific phrase that
    matched (a 2-word phrase like 'undertag diffusionsaaben' is a far stronger
    signal than a bare 'undertag'), so the real material outranks accessories.
    The AI is still told these are keyword candidates and to skip wrong variants."""
    phrases = key_phrases(item)
    phrase_toks = [(p.split()) for p in phrases]
    exclude = [norm(x) for x in item.get("exclude", [])]
    # the material's own head noun(s) — never treat these as accessory words
    material_words = set(_content_tokens(item["name"])) | {
        t for s in item.get("synonyms", []) for t in _content_tokens(s)
    }
    cu = item["unit"].lower()
    band = SANE_UNIT_BAND.get(cu)
    cov = item.get("coverage") or {}

    def derived_unit_price(pr):
        """Rough per-catalog-unit price for the sanity band (mirrors the app)."""
        pk = parse_pack(pr.get("name", ""))
        price = pr["price"]
        if pk and pk["q"] > 0:
            pu = pk["u"]
            if (cu, pu) in {("m2", "m2"), ("m", "m"), ("liter", "l"), ("kg", "kg"), ("pcs", "pcs")}:
                return price / pk["q"]
            if cu in ("roll", "bag", "box", "set"):
                return price
        if cu == "m2" and cov.get("per_m2"):
            return price * cov["per_m2"]
        if cu == "m" and cov.get("per_m"):
            return price * cov["per_m"]
        if cu == "m2" and cov.get("m2_per_unit"):
            return price / cov["m2_per_unit"]
        if cu in ("roll", "bag", "box", "set", "pcs"):
            return price
        return None

    hits = []
    seen = set()
    for pr in prods:
        title = pr["_norm"]
        if exclude and any(x and x in title for x in exclude):
            continue
        best = 0
        for toks in phrase_toks:
            if toks and all(t in title for t in toks):
                best = max(best, len(toks))
        if best == 0:
            continue

        # accessory guard: if the FIRST content word of the title is an accessory
        # term (and not one of this material's own words), it's the wrong row.
        head = next((t for t in _content_tokens(pr.get("name", "")) if t not in STOP), "")
        if head in ACCESSORY and head not in material_words:
            continue

        # unit-band guard
        if band:
            up = derived_unit_price(pr)
            if up is not None and not (band[0] <= up <= band[1]):
                continue

        dedup = (pr["chain"], round(pr["price"]), pr["_norm"][:44])
        if dedup in seen:
            continue
        seen.add(dedup)
        pr = dict(pr)
        pr["_score"] = best
        hits.append(pr)

    # If any product matched a multi-word phrase, drop the bare single-word
    # matches entirely — they're almost always a different product.
    if any(h["_score"] >= 2 for h in hits):
        hits = [h for h in hits if h["_score"] >= 2]
    return hits


def main():
    keys = json.load(open(os.path.join(HERE, "estimator_keys.json"), encoding="utf-8"))
    prods = load_products()
    today = date.today().isoformat()

    out = []
    with_products = 0
    for item in keys:
        entry = {
            "key": item["key"],
            "name": item["name"],
            "synonyms": item.get("synonyms", []),
            "unit": item["unit"],
        }
        if item.get("coverage"):
            entry["coverage"] = item["coverage"]
        hits = match_products(item, prods)
        if hits:
            def rank(h):
                pack = parse_pack(h.get("name", ""))
                return (
                    -h.get("_score", 0),                          # most specific match first
                    0 if h.get("in_stock") is not False else 1,   # in-stock first
                    0 if pack else 1,                              # parsed pack first
                    h["price"],                                    # cheaper first
                )
            hits.sort(key=rank)
            # spread across chains: take best-ranked per chain first, then fill
            by_chain = defaultdict(list)
            for h in hits:
                by_chain[h["chain"]].append(h)
            picked = []
            i = 0
            while len(picked) < MAX_PRODUCTS_PER_KEY and any(by_chain.values()):
                for c in list(by_chain):
                    if by_chain[c]:
                        picked.append(by_chain[c].pop(0))
                        if len(picked) >= MAX_PRODUCTS_PER_KEY:
                            break
                i += 1
                if i > 20:
                    break
            products = []
            for h in picked:
                pk = parse_pack(h.get("name", ""))
                p = {
                    "t": h.get("name", "").strip(),
                    "p": round(h["price"], 2),
                    "c": h["chain"],
                }
                if h.get("url"):
                    p["u"] = h["url"]
                if pk:
                    p["pack"] = pk
                products.append(p)
            entry["products"] = products
            entry["updated"] = today
            with_products += 1
        out.append(entry)

    dst = os.path.join(LATEST, "estimator_catalog.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    kb = os.path.getsize(dst) // 1024
    print(f"estimator_catalog.json: {len(out)} keys, {with_products} with live "
          f"products ({with_products * 100 // max(1, len(out))}%)  ->  {kb} KB")


if __name__ == "__main__":
    main()
