# Deterministic product matching V1

V1 separates product-family identity from the purchasable pack variant. Matching never depends on
an LLM, embedding service, or vector database.

## Normalization

- Brand and product names are case-folded and tokenized.
- Brand tokens, unit tokens, packaging filler, and standalone quantities are removed from the
  product-family name.
- Pack parsing retains per-unit quantity, normalized base unit, pack count, and total quantity.
- Supported base units are `kg`, `l`, and `piece`.
- Cross-pack forms such as `2 × 250 g`, `5 x 1 kg`, `Pack of 10`, and `500 G Pk40` are explicit.

## Decision rules

1. Incompatible base units are discarded.
2. Conflicting non-empty brands are discarded.
3. Remaining family names are ranked by deterministic token Jaccard score with a stable UUID
   tie-break.
4. Verified brand, strong family score, and exact total pack quantity produce `AUTO_MATCH`.
5. A plausible family with a different pack produces family-level `REVIEW`, not a false variant
   match.
6. Missing brands cannot produce automatic matches.
7. Weak, conflicting, or incompatible candidates produce `NO_MATCH`.

Every stored decision records method, confidence, review status, and match time. Manual review can
replace the current decision with `MANUAL_MATCH` without changing historical price observations.

## Reviewed benchmark

The initial labeled fixture contains six cases: one positive automatic match, two negative cases,
one incompatible-unit case, one cross-pack family case, and one empty-brand ambiguous case. The
current deterministic matcher classifies all six expected review states correctly and emits exactly
one automatic match. This is a fixture result, not a claim about production precision or recall.

The benchmark lives at `tests/fixtures/matching/benchmark.json` and runs in the default test suite.
It must grow through reviewed examples before broader accuracy claims are made.

