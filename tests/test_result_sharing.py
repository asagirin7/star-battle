import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import main
from models import Clear, Game
from test_app import client, register, solved, start, star


def test_official_clear_result_is_public_but_attempt_and_identity_stay_private(client):
    owner=register(client,'公開クリア名')
    game=start(client)
    assert game['clear_id'] is None
    with Session(main.engine) as db:
        db.get(Game,game['id']).started_at-=42
        db.commit()
    result=solved(client,game)
    clear_id=result['game']['clear_id']
    assert result['game']['completed'] and clear_id
    with Session(main.engine) as db:
        stored=db.scalar(select(Clear).where(Clear.game_id==game['id']))
        expected=dict(id=stored.id,name=owner['name'],seconds=stored.seconds,
                      points=stored.points,cleared_at=stored.cleared_at,puzzle=game['puzzle'])
        assert stored.seconds>=42
    with TestClient(main.app) as visitor:
        public=visitor.get('/api/clears/'+clear_id)
        assert public.status_code==200
        assert public.json()==expected
        assert result['game']['seconds']==expected['seconds']
        assert 'solution' not in public.text and game['id'] not in public.text
        assert owner['id'] not in public.text and 'memos' not in public.text
        assert visitor.get('/api/games/'+game['id']).status_code==401
        register(visitor,'別プレイヤー')
        assert visitor.get('/api/games/'+game['id']).status_code==404
        assert visitor.get('/api/clears/'+clear_id).json()==expected
    reopened=client.post('/api/games',json={'request_id':str(uuid.uuid4()),
                                           'puzzle_id':game['puzzle']['id']}).json()
    assert reopened['clear_id']==clear_id and reopened['seconds']==expected['seconds']
    repeated=star(client,reopened,0,0)
    assert repeated['player']['points']==expected['points']
    assert repeated['game']['clear_id']==clear_id
    with Session(main.engine) as db:
        assert len(db.scalars(select(Clear)).all())==1


def test_unknown_invalid_and_unfinished_clear_results_are_not_public(client):
    register(client)
    game=start(client)
    for clear_id in ['not-a-uuid',uuid.uuid4().hex,str(uuid.uuid4()),game['id']]:
        response=client.get('/api/clears/'+clear_id)
        assert response.status_code==404
    assert client.get('/api/games/'+game['id']).json()['clear_id'] is None
