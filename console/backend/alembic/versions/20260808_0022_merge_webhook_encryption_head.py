"""Merge the webhook-encryption and Phase 2 migration heads."""

from __future__ import annotations


revision = "20260808_0022"
down_revision = ("20260808_0021", "20260416_0010")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join both migration branches without changing the schema."""


def downgrade() -> None:
    """Split the migration history back into its two parent heads."""
