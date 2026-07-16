"""Links the same product across different sources (e.g. "Amul Butter
Salted" on Deliverit vs "Amul Diced Cheese Blend 1 Kg" on Lots) into a
canonical_products group, so a comparison query can actually compare like
with like instead of four disconnected per-site lists.

Matching is a deliberately simple, fully transparent heuristic -- no ML/
fuzzy-embedding service (keeps this zero-cost and debuggable):

1. Bucket products by (normalized brand, base_unit, pack_qty) -- products
   can only match if they're the same brand and the same parsed pack size.
   This is also why accurate unit parsing (units.py) matters: without it,
   grouping degrades to brand-only matching.
2. Within a bucket, greedily cluster by Jaccard similarity of their
   significant name tokens (brand name and pack-size/packaging words
   stripped out first). Two products join the same canonical group only if
   their token overlap clears SIMILARITY_THRESHOLD.

Recomputed from scratch every run (cheap at a few thousand rows) so
corrected names/brands aren't stuck with a stale grouping decision.
"""
import re
from datetime import datetime, timezone

STOPWORDS = {
    "g", "gm", "gms", "gram", "grams", "kg", "kgs", "kilogram", "kilograms",
    "ml", "l", "ltr", "ltrs", "litre", "liter", "litres", "liters",
    "pack", "pk", "pouch", "btl", "bottle", "box", "jar", "tin", "can",
    "of", "the", "and", "with", "per", "fresh", "new",
    "ea", "pc", "pcs", "piece", "pieces", "unit", "units",
}

_TOKEN_RE = re.compile(r"[a-zA-Z]+")
SIMILARITY_THRESHOLD = 0.5


def _tokenize(name, brand):
    if not name:
        return frozenset()
    text = name.lower()
    if brand:
        text = text.replace(brand.lower(), " ")
    tokens = _TOKEN_RE.findall(text)
    return frozenset(t for t in tokens if len(t) >= 3 and t not in STOPWORDS)


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def rebuild(conn):
    """Recomputes canonical_id for every product row. Returns the number of
    canonical groups created."""
    conn.execute("DELETE FROM canonical_products")
    conn.execute("UPDATE products SET canonical_id = NULL")

    rows = conn.execute("SELECT id, name, brand, pack_qty, base_unit FROM products").fetchall()

    buckets = {}
    for pid, name, brand, pack_qty, base_unit in rows:
        brand_key = (brand or "").strip().lower()
        qty_key = round(pack_qty, 2) if pack_qty is not None else None
        buckets.setdefault((brand_key, base_unit, qty_key), []).append((pid, name, brand))

    ts = datetime.now(timezone.utc).isoformat()
    total_groups = 0
    for (brand_key, base_unit, qty_key), items in buckets.items():
        clusters = []  # each: {"tokens": frozenset, "canonical_id": int}
        for pid, name, brand in items:
            tokens = _tokenize(name, brand)
            match = next(
                (c for c in clusters if _jaccard(tokens, c["tokens"]) >= SIMILARITY_THRESHOLD),
                None,
            )
            if match is None:
                cur = conn.execute(
                    "INSERT INTO canonical_products (canonical_name, brand, pack_qty, base_unit, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (name, brand, qty_key, base_unit, ts),
                )
                match = {"tokens": tokens, "canonical_id": cur.lastrowid}
                clusters.append(match)
                total_groups += 1
            conn.execute("UPDATE products SET canonical_id=? WHERE id=?", (match["canonical_id"], pid))

    conn.commit()
    return total_groups
