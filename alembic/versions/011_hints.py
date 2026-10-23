"""Add per-player launch grants and idempotent explained hint use."""
from alembic import op
import sqlalchemy as sa
revision='011'
down_revision='010'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('hint_wallets',
        sa.Column('player_id',sa.String(36),sa.ForeignKey('players.id'),primary_key=True),
        sa.Column('balance',sa.Integer(),nullable=False),
        sa.Column('grant_day',sa.Integer(),nullable=False))
    op.create_table('hint_uses',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('player_id',sa.String(36),sa.ForeignKey('players.id'),nullable=False),
        sa.Column('game_id',sa.String(36),sa.ForeignKey('games.id'),nullable=False),
        sa.Column('request_id',sa.String(36),nullable=False),
        sa.Column('snapshot',sa.JSON(),nullable=False),
        sa.Column('hint',sa.JSON(),nullable=False),
        sa.UniqueConstraint('player_id','request_id',name='uq_hint_request'))
    op.create_index('ix_hint_uses_player_id','hint_uses',['player_id'])

def downgrade():
    op.drop_table('hint_uses')
    op.drop_table('hint_wallets')
