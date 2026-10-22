"""Index completion time for daily rankings."""
from alembic import op

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_clears_cleared_at', 'clears', ['cleared_at'])


def downgrade():
    op.drop_index('ix_clears_cleared_at', table_name='clears')
