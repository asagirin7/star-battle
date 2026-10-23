import hashlib
import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import main
from models import Account, LoginSession, Player
from test_app import client, register, solved, star, start

CREDENTIALS = {'username':'star_user', 'password':'long-enough-password'}


def account(client):
    response=client.post('/api/account/register',json=CREDENTIALS)
    assert response.status_code==200,response.text
    return response.json()


def test_upgrade_preserves_identity_points_history_and_legacy_cookie_is_retired(client):
    before=register(client)
    game=start(client);solved(client,game)
    guest_token=client.cookies.get('star_player')
    upgraded=account(client)
    assert upgraded['id']==before['id'] and upgraded['points']==3 and upgraded['username']=='star_user'
    assert len(client.get('/api/history').json())==1
    with TestClient(main.app) as device:
        device.cookies.set('star_player',guest_token)
        assert device.get('/api/me').status_code==401
        response=device.post('/api/account/login',json=CREDENTIALS)
        assert response.status_code==200
        assert response.json()==upgraded
        assert device.get('/api/games/current').json()['id']==game['id']
        assert device.get('/api/account/resume').json()['id']==game['id']
        assert len(device.get('/api/history').json())==1
    with Session(main.engine) as db:
        stored=db.get(Account,'star_user')
        assert CREDENTIALS['password'] not in stored.password_hash
        assert stored.password_hash.startswith('scrypt$')
    # Opening a cleared shared puzzle cannot award it twice.
    reopened=client.post('/api/games',json={'request_id':str(uuid.uuid4()),'puzzle_id':game['puzzle']['id']}).json()
    assert reopened['id']==game['id'] and reopened['completed']
    assert client.get('/api/me').json()['points']==3


def test_independent_sessions_logout_expiry_and_password_change(client):
    register(client);account(client)
    original=client.cookies.get('star_player')
    with TestClient(main.app) as device:
        assert device.post('/api/account/login',json={**CREDENTIALS,'username':'STAR_USER'}).status_code==200
        assert device.cookies.get('star_player')!=original
        assert device.post('/api/account/logout',json={}).status_code==200
        device.cookies.set('star_player',original,domain='testserver.local')
        assert device.get('/api/me').status_code==200
        device.post('/api/account/login',json=CREDENTIALS)
        assert client.post('/api/account/password',json={'current_password':'wrong-password','new_password':'another-new-password'}).status_code==401
        assert client.post('/api/account/password',json={'current_password':CREDENTIALS['password'],'new_password':'another-new-password'}).status_code==200
        assert device.get('/api/me').status_code==401
        assert client.get('/api/me').status_code==200
        assert device.post('/api/account/login',json=CREDENTIALS).status_code==401
        assert device.post('/api/account/login',json={**CREDENTIALS,'password':'another-new-password'}).status_code==200
        token=device.cookies.get('star_player')
        with Session(main.engine) as db:
            db.get(LoginSession,hashlib.sha256(token.encode()).hexdigest()).expires_at=time.time()-1
            db.commit()
        assert device.get('/api/me').status_code==401


def test_duplicates_wrong_password_rate_limit_and_csrf(client):
    register(client);account(client)
    with TestClient(main.app) as device:
        guest=register(device)
        duplicate=device.post('/api/account/register',json={**CREDENTIALS,'username':'STAR_USER'})
        assert duplicate.status_code==409
        assert device.get('/api/me').json()['id']==guest['id']
        assert device.get('/api/me').json()['username'] is None
        for _ in range(10):
            assert device.post('/api/account/login',json={**CREDENTIALS,'password':'bad-password'}).status_code==401
        assert device.post('/api/account/login',json=CREDENTIALS).status_code==429
        assert device.post('/api/account/logout',json={},headers={'Origin':'https://other.example'}).status_code==403
        assert device.post('/api/account/login',json={'username':'a','password':'short'}).status_code==422


def test_shared_problem_is_public_but_attempts_scores_and_memos_are_private(client):
    original=register(client);game=start(client);account(client)
    pid=game['puzzle']['id']
    with TestClient(main.app) as friend:
        public=friend.get('/api/puzzles/'+pid)
        assert public.status_code==200
        assert set(public.json())=={'id','size','difficulty','points','multiplier','initial_lives','scoring','regions'}
        assert 'solution' not in public.text
        assert friend.get('/api/games/'+game['id']).status_code==401
        register(friend,'友達')
        assert friend.post('/api/games/'+game['id']+'/memos',json={'changes':{'0':3}}).status_code==404
        response=friend.post('/api/games',json={'request_id':str(uuid.uuid4()),'puzzle_id':pid})
        assert response.status_code==200,response.text
        attempt=response.json()
        assert attempt['id']!=game['id'] and attempt['puzzle']==game['puzzle']
        assert attempt['stars']==[] and attempt['mistakes']==0
        solved(friend,attempt)
        assert friend.get('/api/me').json()['points']==3
        assert client.get('/api/me').json()['points']==0
        assert client.get('/api/games/'+game['id']).json()['stars']==[]
        retry=friend.post('/api/games',json={'request_id':str(uuid.uuid4()),'puzzle_id':pid}).json()
        assert retry['id']==attempt['id'] and retry['completed']
        assert friend.get('/api/me').json()['points']==3
        assert friend.post('/api/games',json={'request_id':game['id'],'puzzle_id':pid}).status_code==404
        assert friend.get('/api/puzzles/'+'0'*32).status_code==404


def test_memos_merge_cell_edits_on_two_devices_and_resume_same_attempt(client):
    register(client);game=start(client);account(client)
    endpoint='/api/games/'+game['id']+'/memos'
    assert client.post(endpoint,json={'changes':{'0':3,'1':2}}).status_code==200
    with TestClient(main.app) as other:
        other.post('/api/account/login',json=CREDENTIALS)
        assert other.get('/api/games/current').json()['id']==game['id']
        assert other.get('/api/games/current').json()['memos'][:2]==[3,2]
        other.post(endpoint,json={'changes':{'2':3}})
        result=client.post(endpoint,json={'changes':{'1':0}}).json()
        assert result['memos'][:3]==[3,0,3] and result['memo_revision']==3
        assert other.get('/api/games/current').json()['memos'][:3]==[3,0,3]
    assert client.post(endpoint,json={'changes':{'0':1}}).status_code==422
    assert client.post(endpoint,json={'changes':{'36':2}}).status_code==422
    assert client.post(endpoint,json={'changes':{'-1':3}}).status_code==422
    assert client.get('/api/games/current').json()['mistakes']==0
