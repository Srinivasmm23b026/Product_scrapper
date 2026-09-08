"""add scrape reauthentication status

Revision ID: 847e137ee787
Revises: 1a9f7d53c4be
Create Date: 2026-09-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "847e137ee787"
down_revision: str | Sequence[str] | None = "1a9f7d53c4be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "status IN ('running', 'complete', 'partial', 'failed', 'suspicious_zero', 'interrupted')"
NEW = (
    "status IN ('running', 'complete', 'partial', 'failed', 'suspicious_zero', "
    "'interrupted', 'reauthentication_required')"
)


def upgrade() -> None:
    with op.batch_alter_table("scrape_runs") as batch_op:
        batch_op.drop_constraint(op.f("ck_scrape_runs_valid_status"), type_="check")
        batch_op.create_check_constraint(op.f("ck_scrape_runs_valid_status"), NEW)


def downgrade() -> None:
    with op.batch_alter_table("scrape_runs") as batch_op:
        batch_op.drop_constraint(op.f("ck_scrape_runs_valid_status"), type_="check")
        batch_op.create_check_constraint(op.f("ck_scrape_runs_valid_status"), OLD)
