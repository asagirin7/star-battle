"""Register validated curated shared boards; preserve user play history on downgrade."""
from alembic import op
from sqlalchemy.orm import Session
from special_boards import install_boards

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    with Session(bind=op.get_bind()) as session:
        install_boards(session)
        session.flush()


def downgrade():
    # These rows may be referenced by games and clears. Keep them intact.
    pass
