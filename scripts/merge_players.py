"""Owner-run maintenance; dry-run by default. Never exposes login credentials."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from config import database_url
from models import Account, Clear, Game, Player


def preview(session, username, source_id):
    account=session.get(Account,username)
    source=session.get(Player,source_id)
    if not account or not source:
        raise ValueError('Account or source player not found')
    target=session.get(Player,account.player_id)
    def summary(p):
        points,count=session.execute(select(func.coalesce(func.sum(Clear.points),0),func.count(Clear.id))
                                     .where(Clear.player_id==p.id)).one()
        return dict(id=p.id,name=p.name,points=points,clears=count,
                    games=session.scalar(select(func.count(Game.id)).where(Game.player_id==p.id)))
    overlaps=session.scalars(select(Clear.puzzle_id).where(Clear.player_id==source.id,
        Clear.puzzle_id.in_(select(Clear.puzzle_id).where(Clear.player_id==target.id)))).all()
    source_account=session.scalar(select(Account).where(Account.player_id==source.id))
    return dict(source=summary(source),target=summary(target),account=username,
                source_has_account=source_account is not None,duplicate_clears=len(overlaps))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--account',required=True)
    parser.add_argument('--source-id',required=True)
    args=parser.parse_args()
    engine=create_engine(database_url(),pool_size=1,max_overflow=0)
    with Session(engine) as session:
        print('PLAYER_MERGE_PREVIEW '+json.dumps(preview(session,args.account,args.source_id),ensure_ascii=False),flush=True)
    engine.dispose()


if __name__=='__main__':
    main()
