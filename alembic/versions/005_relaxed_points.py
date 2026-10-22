"""Set easier 9x9 clears to 50 points without changing other modes."""
from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def set_points(points):
    op.execute(sa.text("UPDATE puzzles SET points = :points WHERE difficulty = 'expert_relaxed'").bindparams(points=points))
    op.execute(sa.text("""UPDATE clears SET points = CASE WHEN mistakes = 0 THEN :points ELSE 0 END
                         WHERE puzzle_id IN (SELECT id FROM puzzles WHERE difficulty = 'expert_relaxed')""").bindparams(points=points))


def upgrade():
    set_points(50)


def downgrade():
    set_points(100)
