from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from procurement_assistant.database import Base
from procurement_assistant.matching import (
    MatchCandidate,
    MatchDecision,
    match_product,
    persist_match_decision,
)
from procurement_assistant.models import ProductMatch, Supplier, SupplierProduct
from procurement_assistant.normalization import normalize_product_name, parse_pack

BENCHMARK = Path(__file__).parent / "fixtures" / "matching" / "benchmark.json"


def test_pack_normalization_preserves_each_count_and_total() -> None:
    case_pack = parse_pack("500 G Pk40")
    assert case_pack.quantity == Decimal("0.5")
    assert case_pack.pack_count == 40
    assert case_pack.total_quantity == Decimal("20")
    assert case_pack.base_unit == "kg"

    cross_pack = parse_pack("2 × 250 g")
    assert cross_pack.quantity == Decimal("0.25")
    assert cross_pack.pack_count == 2
    assert cross_pack.total_quantity == Decimal("0.5")


def test_family_name_removes_brand_and_pack_noise() -> None:
    assert (
        normalize_product_name("Fortune Sunlite Sunflower Oil - 1 L Pouch", "Fortune")
        == "sunlite sunflower oil"
    )


def test_reviewed_matching_benchmark() -> None:
    cases = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    correct = 0
    auto_predictions = 0
    expected_auto = 0
    for case in cases:
        canonical_id = uuid.uuid5(uuid.NAMESPACE_URL, f"canonical:{case['case']}")
        variant_id = uuid.uuid5(uuid.NAMESPACE_URL, f"variant:{case['case']}")
        candidate = MatchCandidate(
            canonical_product_id=canonical_id,
            product_variant_id=variant_id,
            normalized_name=case["candidate_name"],
            canonical_brand=case["candidate_brand"],
            base_unit=case["candidate_unit"],
            total_quantity=Decimal(case["candidate_total"]),
        )
        decision = match_product(
            source_name=case["source_name"],
            source_brand=case["source_brand"],
            source_pack_text=case["source_pack_text"],
            candidates=[candidate],
        )
        correct += decision.review_status == case["expected"]
        auto_predictions += decision.review_status == "AUTO_MATCH"
        expected_auto += case["expected"] == "AUTO_MATCH"
        if case["expected"] == "REVIEW" and "cross pack" in case["case"]:
            assert decision.canonical_product_id == canonical_id
            assert decision.product_variant_id is None

    assert correct == len(cases)
    assert auto_predictions == expected_auto == 1


def test_tie_breaking_is_deterministic() -> None:
    canonical_id = uuid.uuid4()
    candidates = [
        MatchCandidate(
            canonical_product_id=canonical_id,
            product_variant_id=uuid.UUID(int=value),
            normalized_name="basmati rice",
            canonical_brand="Brand",
            base_unit="kg",
            total_quantity=Decimal("1"),
        )
        for value in (2, 1)
    ]
    first = match_product(
        source_name="Brand Basmati Rice 1 kg",
        source_brand="Brand",
        source_pack_text="1 kg",
        candidates=candidates,
    )
    second = match_product(
        source_name="Brand Basmati Rice 1 kg",
        source_brand="Brand",
        source_pack_text="1 kg",
        candidates=list(reversed(candidates)),
    )
    assert first == second


def test_review_and_no_match_decisions_are_persistable_without_variant() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        supplier = Supplier(code="test", name="Test", base_url="https://example.test")
        session.add(supplier)
        session.flush()
        source_product = SupplierProduct(
            supplier_id=supplier.id,
            external_product_id="unmatched",
            source_name="Unknown Product",
        )
        session.add(source_product)
        session.flush()
        decision = MatchDecision(
            canonical_product_id=None,
            product_variant_id=None,
            match_method="no_compatible_candidate",
            confidence=Decimal("0"),
            review_status="NO_MATCH",
        )
        persisted = persist_match_decision(
            session, supplier_product_id=source_product.id, decision=decision
        )
        session.commit()

        stored = session.scalar(select(ProductMatch))
        assert stored.id == persisted.id
        assert stored.product_variant_id is None
        assert stored.review_status == "NO_MATCH"
