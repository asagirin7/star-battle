import random
import uuid

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

import adaptive_difficulty
import main
import special_boards
from models import Base, Puzzle
from puzzle_engine import generate
from test_app import client


def sample():
    board=generate('easy',random.Random(913))
    return dict(board,id='d'*32)


def test_install_idempotent_and_immutable(monkeypatch):
    board=sample()
    monkeypatch.setattr(special_boards,'load_boards',lambda:[board])
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert special_boards.install_boards(session)==[board['id']]
        assert special_boards.install_boards(session)==[]
        assert session.scalar(select(func.count()).select_from(Puzzle))==1
        puzzle=session.get(Puzzle,board['id'])
        view=main.puzzle_view(puzzle)
        assert 'palette' not in view
        assert 'solution' not in view
        puzzle.solution=[0]*board['size']
        with pytest.raises(ValueError,match='different contents'):
            special_boards.install_boards(session)
    engine.dispose()


def test_catalog_is_valid():
    # Validates uniqueness, logical solvability, mode constraints, and IDs.
    for board in special_boards.load_boards():
        assert board['regions'] and 'palette' not in board


def test_catalog_shared_play_and_official_clear(client):
    from test_app import register, solved
    boards=special_boards.load_boards()
    assert boards, 'The special shared board must be registered'
    with Session(main.engine) as session:
        special_boards.install_boards(session)
        session.commit()
    for board in boards:
        public=client.get('/api/puzzles/'+board['id'])
        assert public.status_code==200
        assert 'palette' not in public.json()
        assert 'solution' not in public.json()
    register(client)
    response=client.post('/api/games',json={'request_id':str(uuid.uuid4()),'puzzle_id':boards[0]['id']})
    assert response.status_code==200
    game=response.json()
    result=solved(client,game)
    assert result['game']['completed'] and result['game']['score']==game['puzzle']['points']
    assert game['puzzle']['points']==adaptive_difficulty.RANK_POINTS[game['puzzle']['difficulty_rating']['rank']]
    official=client.get('/api/clears/'+result['game']['clear_id']).json()
    assert official['puzzle']['id']==boards[0]['id']
    assert 'palette' not in official['puzzle']
