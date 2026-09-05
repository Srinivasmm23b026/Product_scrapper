"""model Lots fallback store 101 as one unverified supplier location

Revision ID: 1a9f7d53c4be
Revises: 2f18af8d6023
Create Date: 2026-09-05
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1a9f7d53c4be"
down_revision: str | Sequence[str] | None = "2f18af8d6023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FALLBACK_LOCATION_ID = uuid.UUID("76360d25-4ded-5f3e-b1e0-0a60a1a4b3e4")
FALLBACK_EXTERNAL_ID = "fallback-store:101"
LEGACY_EXTERNAL_IDS = ("legacy:110001", "legacy:560001", "legacy:unresolved")


def _metadata(value):
    if isinstance(value, str):
        return json.loads(value)
    return dict(value or {})


def upgrade() -> None:
    bind = op.get_bind()
    supplier_id = bind.execute(
        sa.text("select id from suppliers where code = :code"), {"code": "lots"}
    ).scalar_one_or_none()
    if supplier_id is None:
        # Fresh schema deployments have no supplier seed data to reconcile.
        return
    supplier_id = uuid.UUID(str(supplier_id))

    locations = sa.table(
        "supplier_locations",
        sa.column("id", sa.Uuid()),
        sa.column("supplier_id", sa.Uuid()),
        sa.column("external_location_id", sa.String()),
        sa.column("location_type", sa.String()),
        sa.column("name", sa.String()),
        sa.column("city", sa.String()),
        sa.column("pincode", sa.String()),
        sa.column("location_metadata", sa.JSON()),
        sa.column("active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    fallback_metadata = {
        "verified": False,
        "resolution_method": "fallback",
        "store_code": "101",
        "location_scope": "supplier_default",
        "failed_pincodes": ["110001", "560001"],
        "location_note": "Public store lookup failed; store 101 is not pincode-specific.",
    }
    existing = bind.execute(
        sa.select(locations.c.id).where(
            locations.c.supplier_id == supplier_id,
            locations.c.external_location_id == FALLBACK_EXTERNAL_ID,
        )
    ).scalar_one_or_none()
    fallback_values = {
        "location_type": "store",
        "name": "Lots fallback store 101 (unverified)",
        "city": None,
        "pincode": None,
        "location_metadata": fallback_metadata,
        "active": True,
    }
    if existing is None:
        bind.execute(
            sa.insert(locations).values(
                id=FALLBACK_LOCATION_ID,
                supplier_id=supplier_id,
                external_location_id=FALLBACK_EXTERNAL_ID,
                created_at=sa.func.now(),
                updated_at=sa.func.now(),
                **fallback_values,
            )
        )
    else:
        bind.execute(
            sa.update(locations)
            .where(locations.c.id == uuid.UUID(str(existing)))
            .values(**fallback_values)
        )

    legacy_rows = bind.execute(
        sa.select(locations.c.id, locations.c.location_metadata).where(
            locations.c.supplier_id == supplier_id,
            locations.c.external_location_id.in_(LEGACY_EXTERNAL_IDS),
        )
    ).all()
    for location_id, metadata in legacy_rows:
        bind.execute(
            sa.update(locations)
            .where(locations.c.id == uuid.UUID(str(location_id)))
            .values(
                active=False,
                location_metadata={
                    **_metadata(metadata),
                    "verified": False,
                    "superseded_by": str(FALLBACK_LOCATION_ID),
                    "supersession_reason": "same_unverified_fallback_store_101",
                },
            )
        )


def downgrade() -> None:
    # Historical location records intentionally remain preserved and inactive.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "update supplier_locations set active = false "
            "where id = :location_id and external_location_id = :external_id"
        ),
        {"location_id": str(FALLBACK_LOCATION_ID), "external_id": FALLBACK_EXTERNAL_ID},
    )
