"""add_email_verification

Add email verification fields for patient registration flow.

- email_verified: boolean flag, default False
- verification_token: UUID token for email verification link
- verification_token_expires: timestamp (24h expiry)

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('email_verified', sa.Boolean(),
                  server_default=sa.text('false'), nullable=False))
    op.add_column('users', sa.Column('verification_token', sa.String(64), nullable=True))
    op.add_column('users', sa.Column('verification_token_expires', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_users_verification_token', 'users', ['verification_token'])


def downgrade() -> None:
    op.drop_index('ix_users_verification_token', 'users')
    op.drop_column('users', 'verification_token_expires')
    op.drop_column('users', 'verification_token')
    op.drop_column('users', 'email_verified')
