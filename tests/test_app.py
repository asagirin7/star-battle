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
    for level in ['easy','medium','hard','expert','expert_relaxed']:
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
                if level == 'expert_relaxed':
                    assert len(cells) >= 2
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


def test_misses_are_revealed_only_after_game_over(client):
    register(client)
    game=start(client)
    answer=solutions(game['puzzle']['regions'])[0]
    wrong=[c for c in range(game['puzzle']['size']) if c!=answer[0]][:3]
    for i,col in enumerate(wrong):
        result=star(client,game,0,col)
        assert result['game']['misses']==([] if i<2 else [[0,c] for c in sorted(wrong)])
    assert client.get('/api/games/'+game['id']).json()['misses']==[[0,c] for c in sorted(wrong)]
    retry=client.post('/api/games/'+game['id']+'/retry',json={}).json()
    assert retry['misses']==[]


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


@pytest.mark.parametrize('level',['expert','expert_relaxed'])
def test_expert_one_mistake_fails_and_clear_has_mode_score(client,level):
    expected=50 if level=='expert_relaxed' else 100
    register(client)
    game=start(client,level)
    assert game['lives']==game['puzzle']['initial_lives']==1
    assert game['puzzle']['points']==expected
    assert game['puzzle']['scoring']=='fixed'
    assert game['puzzle']['multiplier'] is None
    request_id=nonce()
    failed=star(client,game,0,wrong_col(game),request_id)
    assert failed['game']['game_over'] and failed['game']['lives']==0
    repeat=star(client,game,0,wrong_col(game),request_id)
    assert repeat['game']['mistakes']==1
    assert client.get(f'/api/games/current?difficulty={level}').json()['game_over']
    result=solved(client,game)
    assert result['game']['game_over'] and not result['game']['completed']
    assert result['player']['points']==0
    fresh=start(client,level)
    assert fresh['lives']==1
    result=solved(client,fresh)
    assert result['game']['completed'] and result['game']['score']==expected
    assert result['player']['points']==expected
    assert client.get('/api/history').json()[0]['points']==expected
    assert client.get('/api/ranking').json()[0]['points']==expected



@pytest.mark.parametrize('level',['expert','expert_relaxed'])
def test_expert_variants_keep_unique_connected_nontrivial_areas(level):
    from puzzle_engine import valid_area
    seen=set()
    for _ in range(16):
        puzzle=generate(level)
        assert puzzle['points']==LEVELS[level][1]
        assert puzzle['fingerprint'] not in seen
        seen.add(puzzle['fingerprint'])
        assert solutions(puzzle['regions'])==[puzzle['solution']]
        assert all(valid_area(puzzle['regions'],area,level=='expert_relaxed') for area in range(9))
        if level=='expert_relaxed':
            assert sum(sum(row.count(i) for row in puzzle['regions'])==2 for i in range(9))>=2


def test_daily_ranking_uses_japan_midnight_and_completion_time(client,monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from models import Player, Clear
    start_of_day=datetime(2026,10,22,15,tzinfo=timezone.utc).timestamp()
    now=[start_of_day+3600]
    monkeypatch.setattr(main,'time',SimpleNamespace(time=lambda:now[0]))
    with Session(main.engine) as session:
        for ident in ['a','b','c','d','yesterday']:
            session.add(Player(id=ident,name=ident,token_hash=ident))
        session.flush()
        records=[('yesterday',1000,start_of_day-.001),('a',10,start_of_day),
                 ('a',10,start_of_day+1),('b',50,start_of_day+2),
                 ('c',20,start_of_day+3),('d',20,start_of_day+86400-.001),
                 ('d',75,start_of_day+86400)]
        for i,(player_id,points,finished) in enumerate(records):
            session.add(Game(id=f'g{i}',player_id=player_id,puzzle_id=f'p{i}',started_at=start_of_day-90000))
            session.flush()
            session.add(Clear(id=f'c{i}',player_id=player_id,puzzle_id=f'p{i}',game_id=f'g{i}',
                              points=points,mistakes=0,seconds=10,cleared_at=finished))
        session.commit()
    daily=client.get('/api/ranking?period=daily').json()
    assert [(p['id'],p['points'],p['clears']) for p in daily]==[
        ('b',50,1),('a',20,2),('c',20,1),('d',20,1)]
    cumulative=client.get('/api/ranking?period=all').json()
    assert cumulative==client.get('/api/ranking').json()
    assert cumulative[0]['id']=='yesterday' and cumulative[0]['points']==1000
    now[0]=start_of_day+86400
    assert [(p['id'],p['points']) for p in client.get('/api/ranking?period=daily').json()]==[('d',75)]
    now[0]=start_of_day+2*86400
    assert client.get('/api/ranking?period=daily').json()==[]
    assert client.get('/api/ranking?period=weekly').status_code==422



def test_generation_rejects_mismatched_solution_before_save(client,monkeypatch):
    register(client)
    broken=generate('easy',random.Random(99))
    broken['solution']=broken['solution'][1:]+broken['solution'][:1]
    monkeypatch.setattr(main,'generate',lambda difficulty:broken)
    response=client.post('/api/games',json={'difficulty':'easy','request_id':nonce()})
    assert response.status_code==503
    with Session(main.engine) as session:
        assert session.scalar(select(Game.id)) is None


def test_saved_solution_and_incorrect_move_flags_are_repaired(client):
    from models import Move
    register(client)
    game=start(client)
    cols=solutions(game['puzzle']['regions'])[0]
    bad=(cols[0]+1)%6
    with Session(main.engine) as session:
        puzzle=session.get(Puzzle,game['puzzle']['id'])
        puzzle.solution=[(c+1)%6 for c in cols]
        stored=session.get(Game,game['id'])
        stored.mistakes=1
        session.add_all([
            Move(game_id=game['id'],request_id=nonce(),row=0,col=bad,correct=True),
            Move(game_id=game['id'],request_id=nonce(),row=1,col=cols[1],correct=False)])
        session.commit()
    resumed=client.get('/api/games/current').json()
    assert resumed['stars']==[[1,cols[1]]]
    assert resumed['mistakes']==0 and resumed['lives']==3
    with Session(main.engine) as session:
        assert session.get(Puzzle,game['puzzle']['id']).solution==cols
    wrong=star(client,game,0,bad)
    assert not wrong['correct'] and wrong['game']['lives']==2
    result=solved(client,game)
    assert result['game']['completed'] and result['game']['score']==2


@pytest.mark.parametrize('bad_regions',[
    [[0]*6 for _ in range(6)],
    [[r]*6 for r in range(6)],
    [[0,2,2,2,2,2],[2,1,2,2,2,2],[2,2,2,2,2,2],[3]*6,[4]*6,[5]*6],
])
def test_unsolvable_saved_board_is_replaced_without_charging_mistake(client,bad_regions):
    register(client)
    game=start(client)
    with Session(main.engine) as session:
        session.get(Puzzle,game['puzzle']['id']).regions=bad_regions
        session.commit()
    response=client.post(f"/api/games/{game['id']}/stars",json={'row':0,'col':0,'request_id':nonce()})
    assert response.status_code==409
    assert response.json()['detail']['code']=='invalid_puzzle'
    assert client.get('/api/games/current').json() is None
    with Session(main.engine) as session:
        assert session.get(Game,game['id']).mistakes==0
    replacement=start(client)
    assert replacement['id']!=game['id'] and replacement['lives']==3


def test_independent_rules_reject_conflicts_and_incomplete_clears():
    from puzzle_engine import valid_stars
    puzzle=generate('hard',random.Random(55))
    stars=list(enumerate(puzzle['solution']))
    assert valid_stars(puzzle['regions'],stars,complete=True)
    assert not valid_stars(puzzle['regions'],stars[:-1],complete=True)
    assert not valid_stars(puzzle['regions'],[stars[0],stars[0]])
    r,c=stars[0]
    assert not valid_stars(puzzle['regions'],[(r,c),(r,(c+1)%8)])
    assert not valid_stars(puzzle['regions'],[(r,c),((r+1)%8,c)])
    assert not valid_stars(puzzle['regions'],[(0,0),(1,1)])


def test_shape_styles_include_both_axis_spanning_and_compact():
    from puzzle_engine import _generate,certify_generated,spanning_shapes,valid_stars
    for mode in ['easy','medium','hard','expert','expert_relaxed']:
        for style in ['compact','vertical','horizontal','cross']:
            puzzle=certify_generated(_generate(mode,random.Random(10),style=style))
            shapes=spanning_shapes(puzzle['regions'])
            assert not shapes if style=='compact' else style in shapes
            assert valid_stars(puzzle['regions'],enumerate(puzzle['solution']),complete=True)


def test_expert_bank_injects_new_solution_families(monkeypatch):
    import puzzle_engine as engine
    rng=random.Random(456)
    monkeypatch.setattr(engine.random,'SystemRandom',lambda:rng)
    monkeypatch.setattr(engine,'_expert_seeds',{})
    monkeypatch.setattr(engine,'_recent_families',{})
    monkeypatch.setattr(engine,'_generation_counts',{})
    families=set();profiles=set();fingerprints=set()
    for _ in range(72):
        puzzle=engine.generate('expert_relaxed')
        assert engine.checked_solution(puzzle['regions'])==puzzle['solution']
        families.add(engine.solution_family(puzzle['solution']))
        profiles.update(engine.spanning_shapes(puzzle['regions']))
        assert puzzle['fingerprint'] not in fingerprints
        fingerprints.add(puzzle['fingerprint'])
    assert len(families)>=8
    assert profiles=={'vertical','horizontal','cross'}
