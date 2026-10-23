"""Owner-curated shared boards. Never used by the random generator."""
import json
import re
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from models import Puzzle
from puzzle_engine import certify_generated, fingerprint

CATALOG = Path(__file__).resolve().parent / 'data' / 'special_boards.json'


@lru_cache(maxsize=1)
def load_boards():
    boards=json.loads(CATALOG.read_text())
    identifiers=set()
    for board in boards:
        if not re.fullmatch(r'[a-f0-9]{32}',board['id']) or board['id'] in identifiers:
            raise ValueError('Invalid or duplicate curated board ID')
        identifiers.add(board['id'])
        certify_generated(dict(board,fingerprint=fingerprint(board['regions'])))
        palette=board['palette']
        if len(palette)!=board['size'] or any(not re.fullmatch(r'#[a-fA-F0-9]{6}',c) for c in palette):
            raise ValueError('Invalid curated palette')
    return boards


def install_boards(session):
    """Idempotent and non-destructive; caller owns the transaction."""
    installed=[]
    for board in load_boards():
        values={key:board[key] for key in ('id','difficulty','size','points','regions','solution')}
        values['fingerprint']=fingerprint(board['regions'])
        existing=session.get(Puzzle,board['id'])
        if existing:
            if any(getattr(existing,key)!=value for key,value in values.items()):
                raise ValueError('Curated board ID already has different contents')
            continue
        if session.scalar(select(Puzzle.id).where(Puzzle.fingerprint==values['fingerprint'])):
            raise ValueError('Curated layout already registered under another ID')
        session.add(Puzzle(**values))
        session.flush()
        installed.append(board['id'])
    return installed


def palette_for(puzzle):
    for board in load_boards():
        if puzzle.id==board['id'] and puzzle.regions==board['regions']:
            return board['palette']
    return None
