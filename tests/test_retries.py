import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
import main
from models import Clear, Game
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
    assert client.post('/api/games/'+second['id']+'/retry',json={}).status_code==409
    assert client.get('/api/me').json()['points']==0
    for period in ['all','daily']:
        assert client.get('/api/ranking?period='+period).json()[0]['points']==0
    with Session(main.engine) as session:
        assert len(session.scalars(select(Game)).all())==3
        assert len(session.scalars(select(Clear)).all())==1


def test_initial_clear_keeps_points_and_cannot_be_retried_or_overwritten(client):
    register(client)
    game=start(client)
    result=solved(client,game)
    assert result['game']['score']==3
    assert client.post('/api/games/'+game['id']+'/retry',json={}).status_code==409
    assert client.get('/api/clears/'+result['game']['clear_id']).json()['retries']==0
    assert client.get('/api/me').json()['points']==3
    with TestClient(main.app) as other:
        register(other,'other')
        assert other.post('/api/games/'+game['id']+'/retry',json={}).status_code==404
