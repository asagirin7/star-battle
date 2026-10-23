"""Accounts, revocable device sessions and synced board memos."""
from alembic import op
import sqlalchemy as sa

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('accounts',
        sa.Column('username', sa.String(32), primary_key=True),
        sa.Column('player_id', sa.String(36), sa.ForeignKey('players.id'), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(256), nullable=False))
    op.create_table('login_sessions',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('player_id', sa.String(36), sa.ForeignKey('players.id'), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False))
    op.create_index('ix_login_sessions_player_id', 'login_sessions', ['player_id'])
    op.create_table('auth_limits',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('window_start', sa.Float(), nullable=False))
    op.create_table('game_memos',
        sa.Column('game_id', sa.String(36), sa.ForeignKey('games.id'), primary_key=True),
        sa.Column('cells', sa.JSON(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False))


def downgrade():
    op.drop_table('game_memos')
    op.drop_table('auth_limits')
    op.drop_index('ix_login_sessions_player_id', table_name='login_sessions')
    op.drop_table('login_sessions')
    op.drop_table('accounts')
