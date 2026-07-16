import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    name TEXT,
    brand TEXT,
    category TEXT,
    price REAL,
    mrp REAL,
    unit TEXT,
    pack_qty REAL,
    base_unit TEXT,
    price_per_unit REAL,
    in_stock INTEGER,
    image_url TEXT,
    product_url TEXT,
    pincode TEXT,
    location_note TEXT,
    canonical_id INTEGER,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(source, external_id, pincode)
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    price REAL,
    mrp REAL,
    price_per_unit REAL,
    in_stock INTEGER,
    pincode TEXT,
    scraped_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    products_seen INTEGER DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS canonical_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    brand TEXT,
    pack_qty REAL,
    base_unit TEXT,
    created_at TEXT NOT NULL
);
"""

# (table, column, type) pairs that must exist. Lets an existing products.db
# from before these fields were added pick them up via ALTER TABLE, instead
# of requiring the user to delete and rebuild the database.
_REQUIRED_COLUMNS = [
    ("products", "pack_qty", "REAL"),
    ("products", "base_unit", "TEXT"),
    ("products", "price_per_unit", "REAL"),
    ("products", "pincode", "TEXT"),
    ("products", "location_note", "TEXT"),
    ("products", "canonical_id", "INTEGER"),
    ("price_history", "price_per_unit", "REAL"),
    ("price_history", "pincode", "TEXT"),
]


def _migrate(conn):
    for table, column, coltype in _REQUIRED_COLUMNS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    conn.commit()


def _migrate_pincode_uniqueness(conn):
    """Rebuild `products` if its UNIQUE constraint predates per-pincode scraping.

    Before location-aware scraping, every source had exactly one fixed
    pincode value, so UNIQUE(source, external_id) was enough. Now that
    BigBasket/Lots are scraped once per configured pincode, that same
    (source, external_id) legitimately recurs once per pincode -- without
    pincode in the key, upsert_product would overwrite pincode A's row with
    pincode B's price instead of keeping both.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='products'"
    ).fetchone()
    if row is None or "UNIQUE(source, external_id, pincode)" in row[0]:
        return
    conn.execute("ALTER TABLE products RENAME TO products_old")
    conn.executescript(SCHEMA)
    conn.execute(
        """
        INSERT INTO products (id, source, external_id, name, brand, category, price, mrp,
                               unit, pack_qty, base_unit, price_per_unit, in_stock,
                               image_url, product_url, pincode, location_note,
                               canonical_id, first_seen, last_seen)
        SELECT id, source, external_id, name, brand, category, price, mrp,
               unit, pack_qty, base_unit, price_per_unit, in_stock,
               image_url, product_url, COALESCE(pincode, ''), location_note,
               canonical_id, first_seen, last_seen
        FROM products_old
        """
    )
    conn.execute("DROP TABLE products_old")
    conn.commit()


def get_connection():
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.executescript(SCHEMA)
    _migrate(conn)
    _migrate_pincode_uniqueness(conn)
    return conn


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def upsert_product(conn, product: dict):
    """product must have: source, external_id, name, brand, category, price,
    mrp, unit, pack_qty, base_unit, price_per_unit, in_stock, image_url,
    product_url, pincode, location_note"""
    ts = now_iso()
    # SQLite treats every NULL in a UNIQUE index as distinct from every other
    # NULL, so a bare `pincode: None` (Hyperpure/Deliverit's no-pincode case)
    # would defeat ON CONFLICT dedup and insert a new row every run instead
    # of updating in place. Coerce to '' so the constraint actually applies.
    product = {**product, "pincode": product.get("pincode") or ""}
    conn.execute(
        """
        INSERT INTO products (source, external_id, name, brand, category, price, mrp,
                               unit, pack_qty, base_unit, price_per_unit, in_stock,
                               image_url, product_url, pincode, location_note,
                               first_seen, last_seen)
        VALUES (:source, :external_id, :name, :brand, :category, :price, :mrp,
                :unit, :pack_qty, :base_unit, :price_per_unit, :in_stock,
                :image_url, :product_url, :pincode, :location_note,
                :ts, :ts)
        ON CONFLICT(source, external_id, pincode) DO UPDATE SET
            name=excluded.name,
            brand=excluded.brand,
            category=excluded.category,
            price=excluded.price,
            mrp=excluded.mrp,
            unit=excluded.unit,
            pack_qty=excluded.pack_qty,
            base_unit=excluded.base_unit,
            price_per_unit=excluded.price_per_unit,
            in_stock=excluded.in_stock,
            image_url=excluded.image_url,
            product_url=excluded.product_url,
            pincode=excluded.pincode,
            location_note=excluded.location_note,
            last_seen=excluded.last_seen
        """,
        {**product, "ts": ts},
    )
    conn.execute(
        """
        INSERT INTO price_history (source, external_id, price, mrp, price_per_unit,
                                    in_stock, pincode, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (product["source"], product["external_id"], product["price"], product["mrp"],
         product["price_per_unit"], product["in_stock"], product["pincode"], ts),
    )


def start_run(conn, source):
    cur = conn.execute(
        "INSERT INTO scrape_runs (source, started_at) VALUES (?, ?)",
        (source, now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id, products_seen, error=None):
    conn.execute(
        "UPDATE scrape_runs SET finished_at=?, products_seen=?, error=? WHERE id=?",
        (now_iso(), products_seen, error, run_id),
    )
    conn.commit()
