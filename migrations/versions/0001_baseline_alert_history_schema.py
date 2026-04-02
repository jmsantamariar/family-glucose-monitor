"""Baseline: alert_history schema as of Iteration 3.

This is a *baseline* migration — it records the current physical schema so
that future incremental migrations have a known starting point.  The
``upgrade()`` function uses ``IF NOT EXISTS`` guards (via SQLAlchemy's
``checkfirst=True``) so it is safe to run against both fresh and existing
databases.

Physical schema captured here:

.. code-block:: sql

    CREATE TABLE alerts (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp     TEXT NOT NULL,
        patient_id    TEXT NOT NULL,
        patient_name  TEXT NOT NULL,
        glucose_value INTEGER NOT NULL,
        level         TEXT NOT NULL,
        trend_arrow   TEXT NOT NULL DEFAULT '',
        message       TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX idx_alerts_timestamp          ON alerts(timestamp);
    CREATE INDEX idx_alerts_patient_timestamp  ON alerts(patient_id, timestamp);

Revision ID: 0001
Revises:
Create Date: 2026-04-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the alerts table and its indexes if they do not already exist.

    Safe to run against an existing database — ``checkfirst=True`` is
    equivalent to ``CREATE TABLE IF NOT EXISTS``.
    """
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.Text, nullable=False),
        sa.Column("patient_id", sa.Text, nullable=False),
        sa.Column("patient_name", sa.Text, nullable=False),
        sa.Column("glucose_value", sa.Integer, nullable=False),
        sa.Column("level", sa.Text, nullable=False),
        sa.Column("trend_arrow", sa.Text, nullable=False, server_default=""),
        sa.Column("message", sa.Text, nullable=False, server_default=""),
        if_not_exists=True,
    )
    op.create_index(
        "idx_alerts_timestamp",
        "alerts",
        ["timestamp"],
        if_not_exists=True,
    )
    op.create_index(
        "idx_alerts_patient_timestamp",
        "alerts",
        ["patient_id", "timestamp"],
        if_not_exists=True,
    )


def downgrade() -> None:
    """Drop the alerts table (removes all historical alert data).

    .. warning::
       This will permanently delete all stored alert history.
       Only run in development/test environments.
    """
    op.drop_index("idx_alerts_patient_timestamp", table_name="alerts", if_exists=True)
    op.drop_index("idx_alerts_timestamp", table_name="alerts", if_exists=True)
    op.drop_table("alerts", if_exists=True)
