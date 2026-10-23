import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import main
from models import Account, Clear, Game, GameMemo, Move, Player, PlayerMerge
from player_maintenance import consolidate, preview
from test_app import client, register, solved, start, star
from test_accounts_sharing import account, CREDENTIALS


def prepare(client):
    source=register(client,'Administrator')
    guest_token=client.cookies.get('star_player')
    source_game=start(client)
    solved(client,source_game)
    pending=start(client,'medium')
    with Session(main.engine) as db:
        db.add(GameMemo(game_id=pending['id'],cells=[3]+[0]*48,revision=1));db.commit()
    return source,guest_token,source_game,pending


def test_merge_preserves_credentials_scores_games_memos_and_old_device(client):
    source,token,old,pending=prepare(client)
    with TestClient(main.app) as destination:
        target=register(destination,'account name')
        account(destination)
        target_game=start(destination)
        solved(destination,target_game)
        login_token=destination.cookies.get('star_player')
        with Session(main.engine) as db:
            info=preview(db,CREDENTIALS['username'],source['id'])
            assert info['source']['points']==3 and info['target']['points']==3
            result=consolidate(db,CREDENTIALS['username'],source['id'],target['id'],'Administrator')
            db.commit()
            assert result['target']['points']==6
            assert db.get(PlayerMerge,source['id']).backup['clears']
            assert db.get(Game,pending['id']).player_id==target['id']
            assert db.get(GameMemo,pending['id']).cells[0]==3
            assert db.scalar(select(Account).where(Account.player_id==target['id'])).username==CREDENTIALS['username']
            assert consolidate(db,CREDENTIALS['username'],source['id'],target['id'],'Administrator')['already_merged']
            db.commit()
        assert destination.cookies.get('star_player')==login_token
        assert destination.get('/api/me').json()['points']==6
        assert client.cookies.get('star_player')==token
        merged=client.get('/api/me').json()
        assert merged['id']==target['id'] and merged['username']==CREDENTIALS['username']
        assert merged['legacy_player_ids']==[source['id']]
        assert merged['name']=='Administrator' and merged['points']==6
        assert client.get('/api/games/'+pending['id']).json()['memos'][0]==3
        assert len(client.get('/api/history').json())==2
        assert len(client.get('/api/ranking').json())==1
        assert destination.post('/api/account/login',json=CREDENTIALS).status_code==200
        assert destination.post('/api/account/password',json={'current_password':CREDENTIALS['password'],'new_password':'changed-merge-password'}).status_code==200
        assert client.get('/api/me').status_code==401


def test_duplicate_board_keeps_one_award_and_reopening_does_not_reaward(client):
    source,token,game,pending=prepare(client)
    with TestClient(main.app) as destination:
        target=register(destination);account(destination)
        shared=destination.post('/api/games',json={'request_id':__import__('uuid').uuid4().hex,'puzzle_id':game['puzzle']['id']}).json()
        solved(destination,shared)
        with Session(main.engine) as db:
            result=consolidate(db,CREDENTIALS['username'],source['id'],target['id'],'Administrator')
            db.commit()
            assert result['target']['points']==3 and result['removed_duplicate_clears']==1
            assert db.scalar(select(Clear).where(Clear.player_id==source['id'])) is None
            assert len(db.get(PlayerMerge,source['id']).backup['clears'])==2
        # Both old completed game URLs remain terminal, not second scoring opportunities.
        for candidate in [game,shared]:
            state=destination.get('/api/games/'+candidate['id']).json()
            assert state['completed']
            outcome=star(destination,candidate,0,0)
            assert outcome['player']['points']==3
        again=destination.post('/api/games',json={'request_id':__import__('uuid').uuid4().hex,'puzzle_id':game['puzzle']['id']}).json()
        assert again['completed']
        assert destination.get('/api/me').json()['points']==3


def test_identity_mismatch_refuses_and_transaction_rolls_back(client):
    source,token,game,pending=prepare(client)
    with TestClient(main.app) as destination:
        target=register(destination);account(destination)
        with Session(main.engine) as db:
            with pytest.raises(ValueError,match='identity'):
                consolidate(db,CREDENTIALS['username'],source['id'],'wrong-id','Administrator')
            db.rollback()
            with pytest.raises(ValueError,match='Source identity'):
                consolidate(db,CREDENTIALS['username'],source['id'],target['id'],'wrong-name')
            db.rollback()
            assert db.get(Game,game['id']).player_id==source['id']
            assert db.get(PlayerMerge,source['id']) is None
        assert client.get('/api/me').json()['points']==3
        assert destination.get('/api/me').json()['points']==0
