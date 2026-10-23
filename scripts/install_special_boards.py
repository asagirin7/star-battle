"""Validate and register owner-curated shared boards without changing existing rows."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from config import database_url
from special_boards import install_boards

if __name__=='__main__':
    with create_engine(database_url()).begin() as connection:
        with Session(bind=connection) as session:
            installed=install_boards(session)
            session.flush()
    print('Registered shared boards:',', '.join(installed) or 'already installed')
