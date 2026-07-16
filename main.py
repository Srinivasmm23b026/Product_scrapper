import logging
import sys
from pathlib import Path

import canonicalize
import db
from scrapers import bigbasket, deliverit, hyperpure, lots

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")

SCRAPERS = {
    "hyperpure": hyperpure.scrape,
    "bigbasket": bigbasket.scrape,
    "deliverit": deliverit.scrape,
    "lots": lots.scrape,
}


def run_all():
    conn = db.get_connection()
    total = 0
    for source, scrape_fn in SCRAPERS.items():
        run_id = db.start_run(conn, source)
        try:
            products = scrape_fn()
            for p in products:
                db.upsert_product(conn, p)
            conn.commit()
            db.finish_run(conn, run_id, len(products))
            logger.info("%s: stored %d products", source, len(products))
            total += len(products)
        except Exception as exc:
            logger.exception("%s: run failed", source)
            db.finish_run(conn, run_id, 0, error=str(exc))

    n_groups = canonicalize.rebuild(conn)
    logger.info("Canonical grouping: %d groups across %d products", n_groups, total)

    conn.close()
    logger.info("Run complete. Total products upserted: %d", total)


if __name__ == "__main__":
    run_all()
