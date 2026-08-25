from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

NUMBER = r"\d+(?:\.\d+)?"
UNIT_PATTERN = r"kg|kilograms?|g|gm|grams?|l|ltr|lit(?:re|er)s?|ml|pcs?|pieces?|ea|units?|nos"
MEASURE_RE = re.compile(rf"({NUMBER})\s*({UNIT_PATTERN})\b", re.IGNORECASE)
MULTIPACK_RE = re.compile(
    rf"({NUMBER})\s*[x×]\s*({NUMBER})\s*({UNIT_PATTERN})\b", re.IGNORECASE
)
PACK_OF_RE = re.compile(r"\bpack\s+of\s+(\d+)\b", re.IGNORECASE)
PK_RE = re.compile(r"\bpk\s*(\d+)\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-z0-9]+")

NAME_STOPWORDS = {
    "and",
    "bottle",
    "box",
    "can",
    "fresh",
    "gm",
    "jar",
    "kg",
    "kilogram",
    "l",
    "litre",
    "ml",
    "of",
    "pack",
    "pc",
    "pcs",
    "piece",
    "pouch",
    "the",
    "unit",
}


@dataclass(frozen=True, slots=True)
class NormalizedPack:
    quantity: Decimal
    base_unit: str
    pack_count: int
    total_quantity: Decimal
    normalized_text: str


def _unit_factor(unit: str) -> tuple[Decimal, str]:
    unit = unit.lower()
    if unit in {"kg", "kilogram", "kilograms"}:
        return Decimal("1"), "kg"
    if unit in {"g", "gm", "gram", "grams"}:
        return Decimal("0.001"), "kg"
    if unit in {"l", "ltr", "litre", "liter", "litres", "liters"}:
        return Decimal("1"), "l"
    if unit == "ml":
        return Decimal("0.001"), "l"
    return Decimal("1"), "piece"


def parse_pack(*texts: str | None) -> NormalizedPack | None:
    try:
        for raw in texts:
            if not raw:
                continue
            text = raw.strip()
            multipack = MULTIPACK_RE.search(text)
            if multipack:
                pack_count = int(Decimal(multipack.group(1)))
                factor, base_unit = _unit_factor(multipack.group(3))
                quantity = Decimal(multipack.group(2)) * factor
                total = quantity * pack_count
                return _pack(quantity, base_unit, pack_count, total)

            measure = MEASURE_RE.search(text)
            if measure:
                factor, base_unit = _unit_factor(measure.group(2))
                quantity = Decimal(measure.group(1)) * factor
                explicit_pack = PK_RE.search(text) or PACK_OF_RE.search(text)
                pack_count = int(explicit_pack.group(1)) if explicit_pack else 1
                total = quantity * pack_count
                return _pack(quantity, base_unit, pack_count, total)

            pack_only = PACK_OF_RE.search(text)
            if pack_only:
                pack_count = int(pack_only.group(1))
                return _pack(Decimal("1"), "piece", pack_count, Decimal(pack_count))
    except (InvalidOperation, ValueError, OverflowError):
        return None
    return None


def _pack(
    quantity: Decimal, base_unit: str, pack_count: int, total: Decimal
) -> NormalizedPack | None:
    if quantity <= 0 or total <= 0 or pack_count <= 0:
        return None
    quantity = quantity.normalize()
    total = total.normalize()
    suffix = f" x {pack_count}" if pack_count > 1 else ""
    return NormalizedPack(
        quantity=quantity,
        base_unit=base_unit,
        pack_count=pack_count,
        total_quantity=total,
        normalized_text=f"{quantity} {base_unit}{suffix}",
    )


def normalize_brand(brand: str | None) -> str:
    return " ".join(TOKEN_RE.findall((brand or "").casefold()))


def normalize_product_name(name: str, brand: str | None = None) -> str:
    normalized_brand = normalize_brand(brand)
    tokens = TOKEN_RE.findall(name.casefold())
    brand_tokens = set(normalized_brand.split())
    significant = [
        token
        for token in tokens
        if token not in brand_tokens
        and token not in NAME_STOPWORDS
        and not token.isdigit()
        and not re.fullmatch(r"pk\d+", token)
    ]
    return " ".join(significant)

