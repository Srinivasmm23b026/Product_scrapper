import pytest

from scrapers.units import parse_unit, unit_price


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("500 g", (0.5, "kg")),
        ("2 x 250 g", (0.5, "kg")),
        ("2 × 250 g", (0.5, "kg")),
        ("5 x 1 kg", (5.0, "kg")),
        ("12 pcs", (12.0, "pc")),
        ("Pack of 10", (10.0, "pc")),
        ("1.5 L", (1.5, "l")),
        ("750 ml", (0.75, "l")),
        ("25 KG", (25.0, "kg")),
        ("500 G Pk40", (20.0, "kg")),
    ],
)
def test_required_pack_formats(text, expected) -> None:
    assert parse_unit(text) == expected


def test_parser_falls_back_across_text_fields() -> None:
    assert parse_unit(None, "Oil bottle 2 x 750 ml") == (1.5, "l")


def test_unknown_and_zero_quantity_are_not_priced() -> None:
    assert parse_unit("family pack") == (None, None)
    assert unit_price(100, None, None) is None
    assert unit_price(100, 0, "kg") is None

