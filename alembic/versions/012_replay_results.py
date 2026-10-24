"""Keep practice clear results without changing first-clear rewards."""
from alembic import op
import sqlalchemy as sa
revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('replay_results',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('game_id', sa.String(36), sa.ForeignKey('games.id'), nullable=False, unique=True),
        sa.Column('seconds', sa.Integer(), nullable=False),
        sa.Column('cleared_at', sa.Float(), nullable=False))
    # Past account merges kept deleted duplicate clears in the audit backup.
    # Restore them as non-scoring results so their game and public URLs remain
    # terminal even though completion is now checked per attempt.
    connection = op.get_bind()
    merges = sa.table('player_merges', sa.column('backup', sa.JSON()))
    clears = sa.table('clears', sa.column('id'), sa.column('game_id'))
    games = sa.table('games', sa.column('id'))
    results = sa.table('replay_results', sa.column('id'), sa.column('game_id'),
                       sa.column('seconds'), sa.column('cleared_at'))
    known_ids = set(connection.scalars(sa.select(clears.c.id)))
    known_games = set(connection.scalars(sa.select(clears.c.game_id)))
    game_ids = set(connection.scalars(sa.select(games.c.id)))
    for backup in connection.scalars(sa.select(merges.c.backup)):
        for clear in (backup or {}).get('clears', []):
            if (clear['id'] not in known_ids and clear['game_id'] not in known_games
                    and clear['game_id'] in game_ids):
                connection.execute(results.insert().values(id=clear['id'],game_id=clear['game_id'],
                    seconds=clear['seconds'],cleared_at=clear['cleared_at']))
                known_ids.add(clear['id'])
                known_games.add(clear['game_id'])


def downgrade():
    op.drop_table('replay_results')
