"""expand product match review states

Revision ID: 6ba66a5a6def
Revises: 412e9051869a
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6ba66a5a6def"
down_revision: str | Sequence[str] | None = "412e9051869a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("product_matches") as batch_op:
        batch_op.drop_constraint(
            "uq_product_matches_supplier_product_id", type_="unique"
        )
        batch_op.add_column(sa.Column("canonical_product_id", sa.Uuid(), nullable=True))
        batch_op.alter_column(
            "product_variant_id", existing_type=sa.Uuid(), nullable=True
        )
        batch_op.create_foreign_key(
            "fk_product_matches_canonical_product_id_canonical_products",
            "canonical_products",
            ["canonical_product_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(
            "uq_product_matches_supplier_product_id", ["supplier_product_id"]
        )
        batch_op.create_index(
            "ix_product_matches_canonical_product_id", ["canonical_product_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("product_matches") as batch_op:
        batch_op.drop_index("ix_product_matches_canonical_product_id")
        batch_op.drop_constraint(
            "uq_product_matches_supplier_product_id", type_="unique"
        )
        batch_op.drop_constraint(
            "fk_product_matches_canonical_product_id_canonical_products", type_="foreignkey"
        )
        batch_op.alter_column(
            "product_variant_id", existing_type=sa.Uuid(), nullable=False
        )
        batch_op.drop_column("canonical_product_id")
        batch_op.create_unique_constraint(
            "uq_product_matches_supplier_product_id",
            ["supplier_product_id", "product_variant_id"],
        )
