"""allow supplier offers with an unknown normalized pack

Revision ID: 2f18af8d6023
Revises: 6ba66a5a6def
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2f18af8d6023"
down_revision: str | Sequence[str] | None = "6ba66a5a6def"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("supplier_offers") as batch_op:
        batch_op.drop_constraint(
            "uq_supplier_offers_supplier_product_id", type_="unique"
        )
        batch_op.alter_column(
            "product_variant_id", existing_type=sa.Uuid(), nullable=True
        )
        batch_op.create_unique_constraint(
            "uq_supplier_offers_supplier_product_id",
            ["supplier_product_id", "supplier_location_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("supplier_offers") as batch_op:
        batch_op.drop_constraint(
            "uq_supplier_offers_supplier_product_id", type_="unique"
        )
        batch_op.alter_column(
            "product_variant_id", existing_type=sa.Uuid(), nullable=False
        )
        batch_op.create_unique_constraint(
            "uq_supplier_offers_supplier_product_id",
            ["supplier_product_id", "product_variant_id", "supplier_location_id"],
        )
