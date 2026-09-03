# Quantity procurement engine

The comparison engine answers a purchase question, not merely a unit-price question. It accepts a
positive required quantity in mass, volume, or count units and evaluates each active offer using its
normalized total pack quantity.

For every eligible offer:

```text
packs_required = ceil(required_quantity / pack_total_quantity)
quantity_purchased = packs_required × pack_total_quantity
excess_quantity = quantity_purchased - required_quantity
total_cost = packs_required × pack_price
normalized_unit_price = pack_price / pack_total_quantity
```

Mass (`g`, `kg`), volume (`ml`, `L`), and count (`piece`, `pcs`, `unit`) inputs normalize to `kg`,
`l`, and `piece`. Offers are excluded with an explicit reason when unavailable, availability is
unknown, price is unknown, pack size is unknown, or the base unit is incompatible.

The result exposes three independent stable rankings:

- lowest total purchase cost,
- lowest normalized unit price,
- lowest excess quantity.

The UI must not merge these labels: a bulk pack can have the lowest unit price while requiring much
more cash and excess stock for a small requirement.

