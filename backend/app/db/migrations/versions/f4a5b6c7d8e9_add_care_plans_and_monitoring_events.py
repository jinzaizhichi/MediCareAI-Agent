"""add_care_plans_and_monitoring_events

Phase 2a: Patient health management infrastructure.

New tables:
- care_plans: treatment/follow-up plans with JSONB task DAG
- monitoring_events: scheduled reminders and alerts

Existing table extended:
- patient_health_profiles: +5 columns (height, weight, allergies, chronic_diseases, current_medications)

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-05
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── care_plans ──
    op.create_table(
        'care_plans',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_session_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agent_sessions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('diagnosis_summary', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='active'),
        sa.Column('tasks', postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('progress_percent', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('created_by', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_care_plans_patient', 'care_plans', ['patient_id'])
    op.create_index('ix_care_plans_status', 'care_plans', ['status'])

    # ── monitoring_events ──
    op.create_table(
        'monitoring_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plan_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('care_plans.id', ondelete='SET NULL'), nullable=True),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('payload', postgresql.JSONB, nullable=True),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('channel', sa.String(20), nullable=True, server_default='email'),
        sa.Column('retry_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_monitoring_events_patient', 'monitoring_events', ['patient_id'])
    op.create_index('ix_monitoring_events_scheduled', 'monitoring_events', ['scheduled_at'],
                    postgresql_where=sa.text("status = 'pending'"))
    op.create_index('ix_monitoring_events_plan', 'monitoring_events', ['plan_id'])

    # ── patient_health_profiles: +5 columns ──
    op.add_column('patient_health_profiles', sa.Column('height', sa.Integer(), nullable=True))
    op.add_column('patient_health_profiles', sa.Column('weight', sa.Integer(), nullable=True))
    op.add_column('patient_health_profiles', sa.Column('allergies', postgresql.JSONB, nullable=True,
                  server_default=sa.text("'[]'::jsonb")))
    op.add_column('patient_health_profiles', sa.Column('chronic_diseases', postgresql.JSONB, nullable=True,
                  server_default=sa.text("'[]'::jsonb")))
    op.add_column('patient_health_profiles', sa.Column('current_medications', postgresql.JSONB, nullable=True,
                  server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    op.drop_column('patient_health_profiles', 'current_medications')
    op.drop_column('patient_health_profiles', 'chronic_diseases')
    op.drop_column('patient_health_profiles', 'allergies')
    op.drop_column('patient_health_profiles', 'weight')
    op.drop_column('patient_health_profiles', 'height')
    op.drop_index('ix_monitoring_events_plan', 'monitoring_events')
    op.drop_index('ix_monitoring_events_scheduled', 'monitoring_events')
    op.drop_index('ix_monitoring_events_patient', 'monitoring_events')
    op.drop_table('monitoring_events')
    op.drop_index('ix_care_plans_status', 'care_plans')
    op.drop_index('ix_care_plans_patient', 'care_plans')
    op.drop_table('care_plans')
