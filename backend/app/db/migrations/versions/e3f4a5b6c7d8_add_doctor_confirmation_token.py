"""add_doctor_confirmation_token

Add doctor confirmation token for admin-approval email flow.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-05
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('doctor_confirmation_token', sa.String(64), nullable=True))
    op.add_column('users', sa.Column('doctor_confirmation_token_expires', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'doctor_confirmation_token_expires')
    op.drop_column('users', 'doctor_confirmation_token')
