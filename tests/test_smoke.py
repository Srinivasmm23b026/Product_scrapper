from pathlib import Path

from scrapers.units import parse_unit, unit_price


def test_all_python_sources_compile() -> None:
    sources = list(Path(".").glob("*.py")) + list(Path("scrapers").glob("*.py"))
    assert sources
    for source in sources:
        compile(source.read_text(encoding="utf-8"), str(source), "exec")


def test_existing_unit_normalization_smoke() -> None:
    assert parse_unit("500 G Pk40") == (20.0, "kg")
    assert parse_unit("750 ml") == (0.75, "l")
    assert parse_unit("Pack of 10") == (10.0, "pc")
    assert unit_price(50, 0.5, "kg") == 100.0

