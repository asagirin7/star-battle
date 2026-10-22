"""Generated puzzles and authoritative, idempotent star attempts."""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('puzzles', sa.Column('id', sa.String(32), primary_key=True),
                    sa.Column('difficulty', sa.String(16), nullable=False),
                    sa.Column('size', sa.Integer(), nullable=False),
                    sa.Column('points', sa.Integer(), nullable=False),
                    sa.Column('regions', sa.JSON(), nullable=False),
                    sa.Column('solution', sa.JSON(), nullable=False),
                    sa.Column('fingerprint', sa.String(64), nullable=False, unique=True))
    op.add_column('games', sa.Column('finished_at', sa.Float(), nullable=True))
    op.add_column('games', sa.Column('mistakes', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('games', sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('games', sa.Column('move_revision', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('clears', sa.Column('mistakes', sa.Integer(), nullable=False, server_default='0'))
    # Existing clears were recorded without mistakes; normalize their old 100/180/280 scale.
    op.execute(sa.text('UPDATE clears SET points = 3 WHERE points IN (100, 180, 280)'))
    op.create_table('moves', sa.Column('id', sa.String(36), primary_key=True),
                    sa.Column('game_id', sa.String(36), sa.ForeignKey('games.id'), nullable=False),
                    sa.Column('request_id', sa.String(36), nullable=False),
                    sa.Column('row', sa.Integer(), nullable=False),
                    sa.Column('col', sa.Integer(), nullable=False),
                    sa.Column('correct', sa.Boolean(), nullable=False),
                    sa.UniqueConstraint('game_id', 'request_id', name='uq_game_request'))
    op.create_index('ix_moves_game_id', 'moves', ['game_id'])


def downgrade():
    op.drop_table('moves')
    op.drop_column('clears', 'mistakes')
    op.drop_column('games', 'move_revision')
    op.drop_column('games', 'active')
    op.drop_column('games', 'mistakes')
    op.drop_column('games', 'finished_at')
    op.drop_table('puzzles')
