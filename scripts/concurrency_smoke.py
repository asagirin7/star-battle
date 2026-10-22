"""Verify serialized lives and single-award completion against a running PostgreSQL app."""
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from puzzle_engine import solutions

BASE_URL=os.getenv('BASE_URL','http://127.0.0.1:8000')

def nonce():
    return str(uuid.uuid4())

with httpx.Client(base_url=BASE_URL,timeout=30) as c:
    c.post('/api/profile',json={'name':'並列送信検証'}).raise_for_status()
    game=c.post('/api/games',json={'difficulty':'easy','request_id':nonce()}).json()
    cols=solutions(game['puzzle']['regions'])[0]
    move={'row':0,'col':(cols[0]+1)%6,'request_id':nonce()}
    url=f"/api/games/{game['id']}/stars"
    with ThreadPoolExecutor(max_workers=8) as executor:
        responses=list(executor.map(lambda _: c.post(url,json=move),range(8)))
    assert all(r.status_code==200 for r in responses),[r.text for r in responses]
    assert all(r.json()['game']['lives']==2 for r in responses)
    for row,col in list(enumerate(cols))[:-1]:
        c.post(url,json={'row':row,'col':col,'request_id':nonce()}).raise_for_status()
    with ThreadPoolExecutor(max_workers=8) as executor:
        responses=list(executor.map(lambda _: c.post(url,json={'row':5,'col':cols[5],'request_id':nonce()}),range(8)))
    assert all(r.status_code==200 for r in responses),[r.text for r in responses]
    assert c.get('/api/me').json()['points']==2
    assert len(c.get('/api/history').json())==1
    fresh=c.post('/api/games',json={'difficulty':'easy','request_id':nonce()}).json()
    wrong=(solutions(fresh['puzzle']['regions'])[0][0]+1)%6
    with ThreadPoolExecutor(max_workers=8) as executor:
        responses=list(executor.map(lambda _: c.post(f"/api/games/{fresh['id']}/stars",json={'row':0,'col':wrong,'request_id':nonce()}),range(8)))
    assert all(r.status_code==200 for r in responses)
    state=c.get('/api/games/current').json()
    assert state['mistakes']==3 and state['lives']==0 and state['game_over']
    assert c.get('/api/me').json()['points']==2
    print('PASS: 8 concurrent retries cost 1 life, 8 final moves award once, game-over caps mistakes at 3')
