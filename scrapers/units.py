"""Parses free-text pack-size strings ("30 KG", "500 Gram", "1 kg", "750 ml",
"100 pc") into a comparable (pack_qty, base_unit) pair, so prices can be
turned into a true unit price (per kg / per litre / per piece) instead of
comparing raw pack prices across different pack sizes.

base_unit is always one of: "kg", "l", "pc". pack_qty is expressed in that
base_unit, e.g. "500 g" -> (0.5, "kg"); "750 ml" -> (0.75, "l");
"100 pc" -> (100.0, "pc").
"""
import re

_NUM = r"\d+(?:\.\d+)?"
_WEIGHT_RE = re.compile(rf"({_NUM})\s*(kg|kilogram|kilograms|g|gm|gram|grams)\b", re.I)
_VOLUME_RE = re.compile(rf"({_NUM})\s*(l|ltr|litre|liter|litres|liters|ml)\b", re.I)
_COUNT_RE = re.compile(rf"({_NUM})\s*(pc|pcs|piece|pieces|ea|nos|unit|units)\b", re.I)
_PACK_OF_RE = re.compile(r"pack\s+of\s+(\d+)", re.I)
# Case/carton multiplier suffix, e.g. "500 G Pk40" = 40 x 500g units in one
# priced line item (seen throughout Lots Wholesale's B2B bulk-pack naming).
# Without this, a case price gets divided by a single unit's weight and
# produces a wildly inflated (or deflated) unit price.
_MULTIPLIER_RE = re.compile(r"\bpk\s*(\d+)\b", re.I)

_WEIGHT_TO_KG = {
    "kg": 1.0, "kilogram": 1.0, "kilograms": 1.0,
    "g": 0.001, "gm": 0.001, "gram": 0.001, "grams": 0.001,
}
_VOLUME_TO_L = {
    "l": 1.0, "ltr": 1.0, "litre": 1.0, "liter": 1.0, "litres": 1.0, "liters": 1.0,
    "ml": 0.001,
}


def parse_unit(*texts):
    """Tries each text in order (e.g. unit string, then product name as a
    fallback) and returns (pack_qty, base_unit) for the first match, or
    (None, None) if nothing parseable is found. Never raises -- this runs
    unattended against messy, uncontrolled source-site text, so any
    unexpected numeric format is treated as "unparseable" rather than
    crashing the whole scrape run."""
    try:
        for text in texts:
            if not text:
                continue
            mm = _MULTIPLIER_RE.search(text)
            if not mm:
                mm = _PACK_OF_RE.search(text)
            multiplier = int(mm.group(1)) if mm else 1

            m = _WEIGHT_RE.search(text)
            if m:
                qty = float(m.group(1)) * _WEIGHT_TO_KG[m.group(2).lower()] * multiplier
                return round(qty, 6), "kg"
            m = _VOLUME_RE.search(text)
            if m:
                qty = float(m.group(1)) * _VOLUME_TO_L[m.group(2).lower()] * multiplier
                return round(qty, 6), "l"
            m = _COUNT_RE.search(text)
            if m:
                return float(m.group(1)) * multiplier, "pc"
            m = _PACK_OF_RE.search(text)
            if m:
                return float(m.group(1)), "pc"
    except (ValueError, OverflowError):
        pass
    return None, None


def unit_price(price, pack_qty, base_unit):
    """Price per base_unit (per kg / per l / per piece), or None if the pack
    size couldn't be parsed. Only comparable between rows with the same
    base_unit -- price-per-kg and price-per-piece are not interchangeable."""
    if price is None or not pack_qty:
        return None
    return round(price / pack_qty, 4)
