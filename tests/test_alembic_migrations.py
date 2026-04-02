"""Tests for the Alembic migration setup.

These tests verify that:
  - The baseline migration runs without error against a fresh SQLite DB.
  - Running the migration twice (upgrade to head twice) is idempotent.
  - The expected table and indexes are present after the migration.
  - The downgrade removes the table cleanly.
"""
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alembic_cfg(db_path: str) -> Config:
    """Return an Alembic Config pointing at *db_path*."""
    ini_path = str(
        Path(__file__).resolve().parent.parent / "alembic.ini"
    )
    cfg = Config(ini_path)
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def test_upgrade_head_creates_alerts_table(tmp_path):
    db = str(tmp_path / "test.db")
    command.upgrade(_alembic_cfg(db), "head")

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'"
        ).fetchone()
    assert row is not None, "alerts table should exist after upgrade"


def test_upgrade_head_creates_indexes(tmp_path):
    db = str(tmp_path / "test.db")
    command.upgrade(_alembic_cfg(db), "head")

    with sqlite3.connect(db) as conn:
        index_names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='alerts'"
            ).fetchall()
        }
    assert "idx_alerts_timestamp" in index_names
    assert "idx_alerts_patient_timestamp" in index_names


def test_upgrade_head_is_idempotent(tmp_path):
    """Calling upgrade head twice should not raise."""
    db = str(tmp_path / "test.db")
    cfg = _alembic_cfg(db)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # second call — must not raise


# ---------------------------------------------------------------------------
# Current revision
# ---------------------------------------------------------------------------


def test_current_revision_is_head_after_upgrade(tmp_path, capsys):
    db = str(tmp_path / "test.db")
    cfg = _alembic_cfg(db)
    command.upgrade(cfg, "head")
    # Alembic prints to stdout directly — capture with capsys + readouterr
    with capsys.disabled():
        pass  # ensure stdout buffer is flushed
    command.current(cfg)
    # Check stdout (Alembic uses print() for current output)
    captured = capsys.readouterr()
    # Alembic may print to stdout or emit via logger; check both
    combined = captured.out + captured.err
    assert "0001" in combined


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def test_downgrade_base_removes_alerts_table(tmp_path):
    db = str(tmp_path / "test.db")
    cfg = _alembic_cfg(db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'"
        ).fetchone()
    assert row is None, "alerts table should be absent after downgrade"


def test_upgrade_after_downgrade_recreates_table(tmp_path):
    """Full round-trip: upgrade → downgrade → upgrade should work."""
    db = str(tmp_path / "test.db")
    cfg = _alembic_cfg(db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'"
        ).fetchone()
    assert row is not None
