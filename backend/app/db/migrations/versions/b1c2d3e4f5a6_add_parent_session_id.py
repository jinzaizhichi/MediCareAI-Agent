"""add_parent_session_id_and_conversation_type

Plan B+C: Add session hierarchy for post-diagnosis conversation.
- parent_session_id: FK to agent_sessions (self-referential)
- CONVERSATION: new AgentSessionType enum value

Revision ID: b1c2d3e4f5a6
Revises: f919ea76667a
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'f919ea76667a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add CONVERSATION to AgentSessionType enum
    op.execute("ALTER TYPE agentsessiontype ADD VALUE IF NOT EXISTS 'CONVERSATION'")

    # 2. Add parent_session_id column
    op.add_column('agent_sessions',
        sa.Column('parent_session_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='Parent diagnosis session (NULL = top-level diagnosis)')
    )
    op.create_foreign_key(
        'fk_agent_sessions_parent_session_id',
        'agent_sessions', 'agent_sessions',
        ['parent_session_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_index('ix_agent_sessions_parent_session_id', 'agent_sessions', ['parent_session_id'])


def downgrade() -> None:
    op.drop_index('ix_agent_sessions_parent_session_id', table_name='agent_sessions')
    op.drop_constraint('fk_agent_sessions_parent_session_id', 'agent_sessions', type_='foreignkey')
    op.drop_column('agent_sessions', 'parent_session_id')
    # Enum values cannot be removed in PostgreSQL without recreating the type
