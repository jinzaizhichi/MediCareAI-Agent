"""add_registration_fields

Registration system phase 1.5:
- users: +11 columns (age, gender, address, education, specialties, years_of_practice)
- user_attachments: new table for doctor credential uploads
- CHECK constraints on age_years (0-120) and age_months (0-11)

Ref: 注册系统工程级设计文档_2026-05-24 §二

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-06-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users: +11 columns (all NULLABLE, backward-compatible) ──
    op.add_column('users', sa.Column('age_years', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('age_months', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('gender', sa.String(10), nullable=True))
    op.add_column('users', sa.Column('province', sa.String(50), nullable=True))
    op.add_column('users', sa.Column('city', sa.String(50), nullable=True))
    op.add_column('users', sa.Column('district', sa.String(50), nullable=True))
    op.add_column('users', sa.Column('street', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('education', sa.String(20), nullable=True))
    op.add_column('users', sa.Column('years_of_practice', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('specialties', sa.String(500), nullable=True))

    # ── CHECK constraints ──
    op.create_check_constraint(
        'chk_age_years', 'users',
        'age_years >= 0 AND age_years <= 120',
    )
    op.create_check_constraint(
        'chk_age_months', 'users',
        'age_months >= 0 AND age_months <= 11',
    )

    # ── user_attachments: new table ──
    op.create_table(
        'user_attachments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_name', sa.String(255), nullable=False),
        sa.Column('file_url', sa.String(500), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.String(50), nullable=True),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('label', sa.String(100), nullable=True),
        sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('verify_note', sa.String(255), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('idx_user_attachments_user', 'user_attachments', ['user_id'])
    op.create_index('idx_user_attachments_category', 'user_attachments', ['category'])


def downgrade() -> None:
    op.drop_table('user_attachments')
    op.drop_constraint('chk_age_months', 'users')
    op.drop_constraint('chk_age_years', 'users')
    op.drop_column('users', 'specialties')
    op.drop_column('users', 'years_of_practice')
    op.drop_column('users', 'education')
    op.drop_column('users', 'street')
    op.drop_column('users', 'district')
    op.drop_column('users', 'city')
    op.drop_column('users', 'province')
    op.drop_column('users', 'gender')
    op.drop_column('users', 'age_months')
    op.drop_column('users', 'age_years')
