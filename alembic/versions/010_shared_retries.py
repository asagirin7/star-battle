"""Persist explicit retries without changing existing clears or awarded points."""
from alembic import op
import sqlalchemy as sa
revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('games') as batch:
        batch.add_column(sa.Column('retry_count',sa.Integer(),nullable=False,server_default='0'))
        batch.add_column(sa.Column('retry_of',sa.String(36),nullable=True))
        batch.create_unique_constraint('uq_games_retry_of',['retry_of'])
    op.add_column('clears',sa.Column('retry_count',sa.Integer(),nullable=False,server_default='0'))

def downgrade():
    with op.batch_alter_table('clears') as batch:
        batch.drop_column('retry_count')
    with op.batch_alter_table('games') as batch:
        batch.drop_constraint('uq_games_retry_of',type_='unique')
        batch.drop_column('retry_of')
        batch.drop_column('retry_count')
