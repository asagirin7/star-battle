import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
import main
import hint_wallet
from models import HintWallet, HintUse
from test_app import client, register, start


def request(game,**extra):
    return {'game_id':game['id'],'request_id':str(uuid.uuid4()),'crosses':[],**extra}


def test_launch_grants_jst_once_and_skips_unopened_days(client,monkeypatch):
    day=[100]
    monkeypatch.setattr(hint_wallet,'jst_day',lambda:day[0])
    assert register(client)['hints']==10
    for _ in range(3):assert client.get('/api/me').json()['hints']==10
    day[0]=101
    assert client.get('/api/me?launch=false').json()['hints']==10
    assert client.get('/api/me').json()['hints']==13
    assert client.get('/api/me').json()['hints']==13
    day[0]=110
    assert client.get('/api/me').json()['hints']==16
    day[0]=105
    assert client.get('/api/me').json()['hints']==16
    # The same account on another authenticated browser never receives a second grant.
    client.post('/api/account/register',json={'username':'hintsuser','password':'long-password'})
    with TestClient(main.app) as other:
        assert other.post('/api/account/login',json={'username':'hintsuser','password':'long-password'}).json()['hints']==16


def test_hint_charge_idempotency_empty_wallet_and_no_deduction(client,monkeypatch):
    register(client);game=start(client)
    hint=dict(technique='single_candidate',points=1,explanation='説明',source_cells=[[0,0]],target_cells=[[0,0]],action='star')
    monkeypatch.setattr(main,'next_hint',lambda *a,**kw:hint)
    body=request(game)
    first=client.post('/api/hints',json=body)
    assert first.status_code==200 and first.json()=={'hint':hint,'balance':9}
    assert client.post('/api/hints',json=body).json()==first.json()
    with Session(main.engine) as session:
        assert len(session.scalars(select(HintUse)).all())==1
    assert client.post('/api/hints',json=dict(body,crosses=[0])).status_code==409
    monkeypatch.setattr(main,'next_hint',lambda *a,**kw:None)
    assert client.post('/api/hints',json=request(game)).status_code==422
    assert client.get('/api/me').json()['hints']==9
    with Session(main.engine) as session:
        session.scalar(select(HintWallet)).balance=0
        session.commit()
    monkeypatch.setattr(main,'next_hint',lambda *a,**kw:hint)
    assert client.post('/api/hints',json=request(game)).status_code==409
    # Replayed success is returned without any further spend, even at zero balance.
    assert client.post('/api/hints',json=body).json()['balance']==0


def test_wrong_crosses_or_foreign_game_cannot_spend_or_reveal_a_false_hint(client):
    from puzzle_engine import checked_solution
    register(client);game=start(client)
    canonical=checked_solution(game['puzzle']['regions'])
    response=client.post('/api/hints',json=request(game,crosses=[canonical[0]]))
    assert response.status_code==422 and '消費なし' in response.json()['detail']
    assert client.get('/api/me').json()['hints']==10
    for crosses in [[-1],[81]]:
        assert client.post('/api/hints',json=request(game,crosses=crosses)).status_code==422
    with TestClient(main.app) as other:
        register(other)
        assert other.post('/api/hints',json=request(game)).status_code==404
        assert other.get('/api/me').json()['hints']==10


def test_grant_day_rolls_over_at_jst_midnight(monkeypatch):
    from datetime import datetime,timezone
    before=datetime(2026,10,23,14,59,59,tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(hint_wallet.time,'time',lambda:before)
    day=hint_wallet.jst_day()
    monkeypatch.setattr(hint_wallet.time,'time',lambda:before+1)
    assert hint_wallet.jst_day()==day+1
