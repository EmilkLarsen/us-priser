#!/usr/bin/env python3
"""Build price comparison across chains + package JSON for the Fixer API.

Reads data/latest/prices.jsonl -> writes:
  data/latest/comparison.json   {name-key: {chain: price}} for matched products
  data/latest/api/prices.json   compact flat file for the estimator backend
"""
import json
import os
import re
import unicodedata
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def norm_key(name: str) -> str:
    """Fuzzy match key: lowercase, strip accents/sizes noise, collapse."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"[^a-z0-9x ]+", " ", s)
    # WxL dimensions are product identity (a 21x120mm plank differs from
    # 21x145mm) — never strip them. Only strip pure sale-format suffixes.
    s = re.sub(r"\b(\d+x\d+([.,]\d+)?x?\d*)\s*(mm|cm|m)\b", r"DIM\1", s)
    s = re.sub(r"\b\d+[.,]?\d*\s*(l|ml|g|kg|stk|pack|rul)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


SIZE_UNITS = ("l", "ml", "kg", "g")


def extract_size(name: str):
    """Canonical size token: '5 L' -> ('l', 5.0); '21x120mm' -> ('dim', ...).
    Cross-chain comparisons must only pair products of the SAME size."""
    s = name or ""
    m = re.search(r"(\d+([.,]\d+)?)\s*(l|ml|kg|g)\b", s, re.I)
    if m:
        val = float(m.group(1).replace(",", "."))
        unit = m.group(3).lower()
        if unit == "ml":
            val, unit = val / 1000, "l"
        if unit == "g":
            val, unit = val / 1000, "kg"
        return (unit, val)
    m = re.search(r"(\d+(?:x\d+)*)\s*(mm|cm|m)\b", s, re.I)
    if m:
        return ("dim", m.group(1) + m.group(2).lower())
    return None


def size_suffix(name: str) -> str:
    sz = extract_size(name)
    return f"|{sz[0]}:{sz[1]}" if sz else ""


def main():
    src = os.path.join(ROOT, "data", "latest", "prices.jsonl")
    by_key = defaultdict(dict)
    meta = {}
    n = 0
    with open(src, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            n += 1
            ean = str(r.get("ean") or "").strip()
            if len(ean) >= 12:
                k = "ean:" + ean
            else:
                k = norm_key(r.get("name", "")) + size_suffix(r.get("name", ""))
            if len(k.replace("ean:", "")) < 8:
                continue
            if r["chain"] not in by_key[k] or r["price"] < by_key[k][r["chain"]]:
                by_key[k][r["chain"]] = r["price"]
            meta.setdefault(k, {"name": r.get("name"), "url": r.get("url")})

    # cross-chain name keys are fuzzy — count how many distinct products fed
    # each key; >1 product from the SAME chain means ambiguous match
    key_products = defaultdict(set)
    with open(src, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ean = str(r.get("ean") or "").strip()
            if len(ean) >= 12:
                k = "ean:" + ean
            else:
                k = norm_key(r.get("name", "")) + size_suffix(r.get("name", ""))
            key_products[k].add(r.get("sku") or r.get("url"))

    comparison = []
    for k, chains in by_key.items():
        if len(chains) < 2:
            continue  # only multi-chain matches are interesting
        n_products = len(key_products.get(k, ()))
        if not k.startswith("ean:") and n_products > len(chains):
            continue  # same product-size variants merged: min() would be biased
        prices = list(chains.values())
        spread = (max(prices) - min(prices)) / min(prices) * 100
        # name-matched pairs with >150% spread are almost always different
        # products (pack sizes, multipacks, different models) — exclude them
        if not k.startswith("ean:") and spread > 150:
            continue
        comparison.append({
            "key": k, "name": meta[k]["name"],
            "prices": chains,
            "min": min(prices), "max": max(prices),
            "spread_pct": round(spread, 1),
            # exact EAN match = trustworthy; fuzzy name match where each chain
            # contributed exactly one product = probable; else ambiguous
            "match": ("exact" if k.startswith("ean:")
                      else ("probable" if n_products == len(chains)
                            else "ambiguous")),
        })
    comparison.sort(key=lambda x: -x["spread_pct"])

    with open(os.path.join(ROOT, "data", "latest", "comparison.json"), "w",
              encoding="utf-8") as f:
        json.dump(comparison[:5000], f, ensure_ascii=False, indent=1)
    if n == 0:
        raise SystemExit("prices.jsonl was empty — nothing scraped? refusing to publish empty feed")

    print(f"{n} rows in, {len(by_key)} unique keys, "
          f"{len(comparison)} multi-chain comparisons")


if __name__ == "__main__":
    main()
