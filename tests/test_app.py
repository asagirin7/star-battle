import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import main
from models import Base
from scripts.generate_puzzles import solutions


@pytest.fixture
def client(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, 'engine', engine)
    with TestClient(main.app) as client:
        yield client
    engine.dispose()


def register(client, name='星あつめ'):
    response = client.post('/api/profile', json={'name':name})
    assert response.status_code == 200
    return response.json()


def finish(client, puzzle):
    game = client.post('/api/games', json={'puzzle_id':puzzle['id']}).json()
    cols = solutions(puzzle['regions'])[0]
    stars = [[r,c] for r,c in enumerate(cols)]
    return game, client.post(f"/api/games/{game['id']}/complete", json={'stars':stars})


def test_catalog_unique_and_connected():
    assert len(main.PUZZLES) == 36
    for p in main.PUZZLES.values():
        result = solutions(p['regions'])
        assert len(result) == 1
        assert main.valid_stars(p, list(enumerate(result[0])))
        for region in range(p['size']):
            cells = {(r,c) for r in range(p['size']) for c in range(p['size']) if p['regions'][r][c] == region}
            visited = {next(iter(cells))}
            while True:
                expanded = visited | {(r+dr,c+dc) for r,c in visited for dr,dc in [(0,1),(0,-1),(1,0),(-1,0)] if (r+dr,c+dc) in cells}
                if expanded == visited: break
                visited = expanded
            assert visited == cells


def test_clear_award_idempotent_history_and_ranking(client):
    register(client)
    puzzle = main.PUZZLES['easy-01']
    game, response = finish(client, puzzle)
    assert response.status_code == 200
    assert response.json()['awarded'] == 100
    _, response = finish(client, puzzle)
    assert response.json()['awarded'] == 0
    assert client.get('/api/me').json()['points'] == 100
    assert len(client.get('/api/history').json()) == 1
    assert client.get('/api/puzzles').json()[0]['cleared']
    assert client.get('/api/ranking').json()[0]['points'] == 100
    register(client, '名前変更')
    assert client.get('/api/me').json()['points'] == 100
    assert client.get('/api/ranking').json()[0]['name'] == '名前変更'


def test_invalid_and_foreign_games_do_not_award(client):
    assert client.get('/api/history').status_code == 401
    register(client)
    game = client.post('/api/games', json={'puzzle_id':'easy-01'}).json()
    for stars in [[], [[0,0]]*6, [[r,r] for r in range(6)], [[-1,0]]*6]:
        assert client.post(f"/api/games/{game['id']}/complete", json={'stars':stars}).status_code == 422
    client.cookies.clear()
    register(client, '別プレイヤー')
    assert client.post(f"/api/games/{game['id']}/complete", json={'stars':[]}).status_code == 404
    assert client.get('/api/me').json()['points'] == 0


def test_csrf_and_validation(client):
    assert client.post('/api/profile', json={'name':'攻撃'}, headers={'Origin':'https://elsewhere.example'}).status_code == 403
    assert client.post('/api/profile', content='{}', headers={'content-type':'text/plain'}).status_code == 415
    assert client.post('/api/profile', json={'name':'   '}).status_code == 422
    assert client.post('/api/profile', json={'name':'a'*25}).status_code == 422
    assert client.get('/').status_code == 200
    assert client.get('/health').json()['status'] == 'ok'
