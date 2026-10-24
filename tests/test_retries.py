import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
import main
from models import Clear, Game, ReplayResult
from puzzle_engine import solutions
from test_app import client, register, start, star, solved


def fail(client,game):
    wrong=(solutions(game['puzzle']['regions'])[0][0]+1)%game['puzzle']['size']
    for _ in range(game['puzzle']['initial_lives']):
        result=star(client,game,0,wrong)
    assert result['game']['game_over']


def test_retry_chain_is_authoritative_resumable_and_never_awards_points(client):
    register(client)
    original=start(client)
    assert client.post('/api/games/'+original['id']+'/retry',json={}).status_code==409
    fail(client,original)
    first=client.post('/api/games/'+original['id']+'/retry',json={}).json()
    assert first['id']!=original['id'] and first['puzzle']==original['puzzle']
    assert first['retries']==1 and first['mistakes']==0 and not first['completed']
    assert client.post('/api/games/'+original['id']+'/retry',json={}).json()['id']==first['id']
    assert client.get('/api/games/'+first['id']).json()['retries']==1
    reopened=client.post('/api/games',json={'request_id':str(uuid.uuid4()),'puzzle_id':original['puzzle']['id']}).json()
    assert reopened['id']==first['id'] and reopened['retries']==1
    fail(client,first)
    second=client.post('/api/games/'+first['id']+'/retry',json={}).json()
    assert second['retries']==2
    # A delayed duplicate for the first failure must never create a third trial.
    assert client.post('/api/games/'+original['id']+'/retry',json={}).json()['id']==first['id']
    result=solved(client,second)
    assert result['game']['completed'] and result['game']['score']==0
    assert result['player']['points']==0
    official=client.get('/api/clears/'+result['game']['clear_id']).json()
    assert official['retries']==2 and official['points']==0
    assert client.post('/api/games/'+second['id']+'/retry',json={}).json()['retries']==3
    assert client.get('/api/me').json()['points']==0
    for period in ['all','daily']:
        assert client.get('/api/ranking?period='+period).json()[0]['points']==0
    with Session(main.engine) as session:
        assert len(session.scalars(select(Game)).all())==4
        assert len(session.scalars(select(Clear)).all())==1


def test_initial_clear_keeps_points_and_replay_has_own_authoritative_result(client):
    register(client)
    game=start(client)
    result=solved(client,game)
    assert result['game']['score']==3
    original_id=result['game']['clear_id']
    original=client.get('/api/clears/'+original_id).json()
    replay=client.post('/api/games/'+game['id']+'/retry',json={}).json()
    assert not replay['completed'] and replay['stars']==[] and replay['retries']==1
    assert replay['score']==0 and replay['clear_id'] is None
    # The old clear must not block hints or make the fresh trial terminal.
    hint=client.post('/api/hints',json={'game_id':replay['id'],'request_id':str(uuid.uuid4()),'crosses':[]})
    assert hint.status_code==200, hint.text
    assert client.post('/api/games/'+game['id']+'/retry',json={}).json()['id']==replay['id']
    with Session(main.engine) as session:
        attempt=session.get(Game,replay['id']);attempt.started_at-=42;session.commit()
    replay_result=solved(client,replay)
    assert replay_result['game']['completed'] and replay_result['game']['score']==0
    assert replay_result['game']['clear_id']!=original_id and replay_result['game']['seconds']>=42
    replay_id=replay_result['game']['clear_id']
    shared=client.get('/api/clears/'+replay_id).json()
    assert shared['points']==0 and shared['retries']==1 and shared['seconds']==replay_result['game']['seconds']
    assert set(shared)==set(original)
    assert client.get('/api/clears/'+original_id).json()==original
    assert client.get('/api/me').json()['streaks']['easy']==1
    reopened=client.post('/api/games',json={'request_id':str(uuid.uuid4()),'puzzle_id':game['puzzle']['id']}).json()
    assert reopened['id']==replay['id'] and reopened['clear_id']==replay_id
    again=client.post('/api/games/'+replay['id']+'/retry',json={}).json()
    assert again['retries']==2 and not again['completed']
    assert client.post('/api/games/'+replay['id']+'/retry',json={}).json()['id']==again['id']
    solved(client,again)
    assert client.get('/api/me').json()['streaks']['easy']==1
    with Session(main.engine) as session:
        assert len(session.scalars(select(Clear)).all())==1
        assert len(session.scalars(select(ReplayResult)).all())==2
    assert client.get('/api/clears/'+result['game']['clear_id']).json()['retries']==0
    assert client.get('/api/me').json()['points']==3
    with TestClient(main.app) as other:
        register(other,'other')
        assert other.post('/api/games/'+game['id']+'/retry',json={}).status_code==404
