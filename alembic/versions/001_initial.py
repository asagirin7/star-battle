"""Players, game attempts, and idempotent clear records."""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('players', sa.Column('id', sa.String(36), primary_key=True),
                    sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
                    sa.Column('name', sa.String(24), nullable=False))
    op.create_table('games', sa.Column('id', sa.String(36), primary_key=True),
                    sa.Column('player_id', sa.String(36), sa.ForeignKey('players.id'), nullable=False),
                    sa.Column('puzzle_id', sa.String(32), nullable=False),
                    sa.Column('started_at', sa.Float(), nullable=False))
    op.create_index('ix_games_player_id', 'games', ['player_id'])
    op.create_table('clears', sa.Column('id', sa.String(36), primary_key=True),
                    sa.Column('player_id', sa.String(36), sa.ForeignKey('players.id'), nullable=False),
                    sa.Column('puzzle_id', sa.String(32), nullable=False),
                    sa.Column('game_id', sa.String(36), sa.ForeignKey('games.id'), nullable=False, unique=True),
                    sa.Column('points', sa.Integer(), nullable=False),
                    sa.Column('seconds', sa.Integer(), nullable=False),
                    sa.Column('cleared_at', sa.Float(), nullable=False),
                    sa.UniqueConstraint('player_id', 'puzzle_id', name='uq_player_puzzle'))
    op.create_index('ix_clears_player_id', 'clears', ['player_id'])


def downgrade():
    op.drop_table('clears')
    op.drop_table('games')
    op.drop_table('players')
