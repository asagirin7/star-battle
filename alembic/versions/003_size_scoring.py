"""Apply board-size multipliers consistently to new and historical clear scores."""
from alembic import op
import sqlalchemy as sa

revision='003'
down_revision='002'
branch_labels=None
depends_on=None


def set_scores(weighted):
    for level,weight in [('easy',1),('medium',2),('hard',3)]:
        factor=weight if weighted else 1
        op.execute(sa.text('UPDATE puzzles SET points = :maximum WHERE difficulty = :level')
                   .bindparams(maximum=3*factor,level=level))
        op.execute(sa.text('''UPDATE clears SET points = CASE WHEN mistakes < 3
                          THEN (3-mistakes)*:factor ELSE 0 END
                          WHERE puzzle_id IN (SELECT id FROM puzzles WHERE difficulty = :level)
                             OR puzzle_id LIKE :legacy''')
                   .bindparams(factor=factor,level=level,legacy=level+'-%'))


def upgrade():
    set_scores(True)


def downgrade():
    set_scores(False)
