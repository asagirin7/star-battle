import random
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import main
from models import Base, Game, Puzzle
from puzzle_engine import fingerprint, generate, solutions, LEVELS


def nonce():
    return str(uuid.uuid4())


@pytest.fixture
def client(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, 'engine', engine)
    with TestClient(main.app) as client:
        yield client
    engine.dispose()


def register(client, name='星あつめ'):
    response = client.post('/api/profile', json={'name': name})
    assert response.status_code == 200
    return response.json()


def start(client, level='easy', request_id=None):
    response = client.post('/api/games', json={'difficulty':level, 'request_id':request_id or nonce()})
    assert response.status_code == 200, response.text
    return response.json()


def star(client, game, row, col, request_id=None):
    response = client.post(f"/api/games/{game['id']}/stars", json={'row':row, 'col':col, 'request_id':request_id or nonce()})
    assert response.status_code == 200, response.text
    return response.json()


def solved(client, game):
    result = None
    for r,c in enumerate(solutions(game['puzzle']['regions'])[0]):
        result = star(client, game, r, c)
    return result


def wrong_col(game):
    return (solutions(game['puzzle']['regions'])[0][0]+1) % game['puzzle']['size']


def test_generated_unique_connected_and_varied():
    for level in ['easy','medium','hard','expert']:
        fingerprints = set()
        for seed in range(6):
            p = generate(level, random.Random(seed))
            assert solutions(p['regions']) == [p['solution']]
            assert p['points'] == LEVELS[level][1]
            assert p['fingerprint'] == fingerprint(p['regions'])
            fingerprints.add(p['fingerprint'])
            n=p['size']
            for region in range(n):
                cells={(r,c) for r in range(n) for c in range(n) if p['regions'][r][c]==region}
                if level == 'expert':
                    assert len(cells) >= 3
                    assert len({r for r,c in cells}) >= 2
                    assert len({c for r,c in cells}) >= 2
                visited={next(iter(cells))}
                while True:
                    expanded=visited | {(r+dr,c+dc) for r,c in visited for dr,dc in [(0,1),(0,-1),(1,0),(-1,0)] if (r+dr,c+dc) in cells}
                    if expanded==visited: break
                    visited=expanded
                assert visited==cells
        assert len(fingerprints)==6


@pytest.mark.parametrize('level,factor', [('easy',1),('medium',2),('hard',3)])
@pytest.mark.parametrize('mistakes,remaining', [(0,3),(1,2),(2,1)])
def test_remaining_lives_are_score(client, mistakes, remaining, level, factor):
    register(client)
    game=start(client,level)
    expected=remaining*factor
    assert game['puzzle']['multiplier']==factor
    assert game['puzzle']['points']==3*factor
    for _ in range(mistakes):
        star(client,game,0,wrong_col(game))
    result=solved(client,game)
    assert result['game']['completed']
    assert result['game']['score']==expected
    assert result['player']['points']==expected
    assert result['game']['mistakes']==mistakes
    assert client.get('/api/ranking').json()[0]['points']==expected
    history=client.get('/api/history').json()
    assert history[0]['mistakes']==mistakes
    assert history[0]['points']==expected


def test_game_over_persists_and_cannot_award(client):
    register(client)
    game=start(client)
    for _ in range(3):
        result=star(client,game,0,wrong_col(game))
    assert result['game']['game_over']
    assert result['game']['lives']==0
    assert client.get('/api/games/current').json()['game_over']
    result=solved(client,game)
    assert not result['game']['completed']
    assert result['player']['points']==0
    assert not client.get('/api/history').json()
    fresh=start(client)
    assert fresh['id'] != game['id']
    assert fresh['lives']==3


def test_retries_locked_stars_and_no_client_side_scoring(client):
    register(client)
    game=start(client)
    request_id=nonce()
    first=star(client,game,0,wrong_col(game),request_id)
    repeat=star(client,game,0,wrong_col(game),request_id)
    assert first['game']['lives']==repeat['game']['lives']==2
    good=solutions(game['puzzle']['regions'])[0][0]
    conflict=client.post(f"/api/games/{game['id']}/stars",json={'row':0,'col':good,'request_id':request_id})
    assert conflict.status_code==409
    star(client,game,0,good)
    again=star(client,game,0,good)
    assert len(again['game']['stars'])==1
    assert again['game']['lives']==2
    current=client.get('/api/games/current').json()
    assert current['mistakes']==1
    assert current['stars']==[[0,good]]
    assert 'solution' not in current['puzzle']
    assert 'fingerprint' not in current['puzzle']
    result=solved(client,game)
    assert result['player']['points']==2
    assert solved(client,game)['player']['points']==2
    assert client.post(f"/api/games/{game['id']}/complete",json={'stars':[],'points':999}).status_code==404


def test_endless_boards_keep_adding_score(client):
    register(client)
    ids=set()
    for _ in range(15):
        game=start(client)
        ids.add(game['puzzle']['id'])
        result=solved(client,game)
    assert len(ids)==15  # Exceeds the old 12-board limit for one difficulty.
    assert result['player']['points']==45
    assert result['player']['clears']==15
    assert len(client.get('/api/history').json())==15
    register(client,'名前変更')
    assert client.get('/api/me').json()['points']==45
    assert client.get('/api/ranking').json()[0]['name']=='名前変更'


def test_start_retry_resume_levels_and_other_player(client):
    register(client)
    request_id=nonce()
    game=start(client,request_id=request_id)
    assert start(client,request_id=request_id)['id']==game['id']
    assert client.get('/api/games/current').json()['id']==game['id']
    medium=start(client,'medium')
    assert medium['puzzle']['size']==7
    assert client.get('/api/games/current?difficulty=medium').json()['id']==medium['id']
    assert client.get('/api/games/current').json()['id']==game['id']
    client.cookies.clear()
    assert client.get('/api/games/current').status_code==401
    register(client,'別プレイヤー')
    assert client.get(f"/api/games/{game['id']}").status_code==404
    assert client.post(f"/api/games/{game['id']}/stars",json={'row':0,'col':0,'request_id':nonce()}).status_code==404
    assert client.post('/api/games',json={'difficulty':'easy','request_id':request_id}).status_code==404


def test_csrf_validation_and_health(client):
    assert client.post('/api/profile',json={'name':'攻撃'},headers={'Origin':'https://elsewhere.example'}).status_code==403
    assert client.post('/api/profile',content='{}',headers={'content-type':'text/plain'}).status_code==415
    assert client.post('/api/profile',json={'name':'   '}).status_code==422
    register(client)
    assert client.post('/api/games',json={'difficulty':'unknown','request_id':nonce()}).status_code==422
    game=start(client)
    for row,col in [(-1,0),(6,0),(0,6),(1.5,0)]:
        assert client.post(f"/api/games/{game['id']}/stars",json={'row':row,'col':col,'request_id':nonce()}).status_code==422
    assert client.get(f"/api/games/{game['id']}").json()['lives']==3
    assert client.get('/health').json()['status']=='ok'


def test_asset_urls_change_with_content_and_revalidate(client):
    response=client.get('/')
    assert 'no-cache' in response.headers['cache-control']
    for asset in main.ASSETS:
        assert f'/static/{asset}?v={main.ASSET_VERSION}' in response.text
        file=client.get(f'/static/{asset}?v={main.ASSET_VERSION}')
        assert file.status_code==200
        assert 'no-cache' in file.headers['cache-control']
    import hashlib
    expected=hashlib.sha256(b''.join((main.ROOT/'static'/name).read_bytes() for name in main.ASSETS)).hexdigest()[:16]
    assert main.ASSET_VERSION==expected


def test_expert_one_mistake_fails_and_clear_is_fixed_30(client):
    register(client)
    game=start(client,'expert')
    assert game['lives']==game['puzzle']['initial_lives']==1
    assert game['puzzle']['points']==30
    assert game['puzzle']['scoring']=='fixed'
    assert game['puzzle']['multiplier'] is None
    request_id=nonce()
    failed=star(client,game,0,wrong_col(game),request_id)
    assert failed['game']['game_over'] and failed['game']['lives']==0
    repeat=star(client,game,0,wrong_col(game),request_id)
    assert repeat['game']['mistakes']==1
    assert client.get('/api/games/current?difficulty=expert').json()['game_over']
    result=solved(client,game)
    assert result['game']['game_over'] and not result['game']['completed']
    assert result['player']['points']==0
    fresh=start(client,'expert')
    assert fresh['lives']==1
    result=solved(client,fresh)
    assert result['game']['completed'] and result['game']['score']==30
    assert result['player']['points']==30
    assert client.get('/api/history').json()[0]['points']==30
    assert client.get('/api/ranking').json()[0]['points']==30
