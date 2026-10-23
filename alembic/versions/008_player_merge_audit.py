"""Audit and aliases for owner-run player consolidations; no automatic merges."""
from alembic import op
import sqlalchemy as sa

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('player_merges',
        sa.Column('source_id', sa.String(36), sa.ForeignKey('players.id'), primary_key=True),
        sa.Column('target_id', sa.String(36), sa.ForeignKey('players.id'), nullable=False),
        sa.Column('completed_at', sa.Float(), nullable=False),
        sa.Column('backup', sa.JSON(), nullable=False))
    op.create_index('ix_player_merges_target_id','player_merges',['target_id'])


def downgrade():
    op.drop_index('ix_player_merges_target_id',table_name='player_merges')
    op.drop_table('player_merges')
