"""Transactional consolidation invoked only by the application owner via CLI."""
from collections import defaultdict
import hashlib
import secrets
import time
from sqlalchemy import func, select, update
from models import Account, Clear, Game, GameMemo, LoginSession, Move, Player, PlayerMerge, Puzzle


def summary(session, p):
    points,count=session.execute(select(func.coalesce(func.sum(Clear.points),0),func.count(Clear.id))
                                 .where(Clear.player_id==p.id)).one()
    return dict(id=p.id,name=p.name,points=points,clears=count,
                games=session.scalar(select(func.count(Game.id)).where(Game.player_id==p.id)))


def preview(session, username, source_id):
    account=session.get(Account,username)
    source=session.get(Player,source_id)
    if not account or not source:
        raise ValueError('Account or source player not found')
    target=session.get(Player,account.player_id)
    overlaps=session.scalars(select(Clear.puzzle_id).where(Clear.player_id==source.id,
        Clear.puzzle_id.in_(select(Clear.puzzle_id).where(Clear.player_id==target.id)))).all()
    source_account=session.scalar(select(Account).where(Account.player_id==source.id))
    return dict(source=summary(session,source),target=summary(session,target),account=username,
                source_has_account=source_account is not None,duplicate_clears=len(overlaps))


def consolidate(session, username, source_id, expected_target_id, expected_source_name):
    account=session.get(Account,username)
    if not account or account.player_id!=expected_target_id:
        raise ValueError('Destination account identity changed')
    if source_id==expected_target_id:
        raise ValueError('Source and destination must differ')
    # Deterministic lock order; stars/notes on either identity finish before transfer.
    for player_id in sorted([source_id,expected_target_id]):
        session.execute(update(Player).where(Player.id==player_id).values(name=Player.name))
    source=session.get(Player,source_id,populate_existing=True)
    target=session.get(Player,expected_target_id,populate_existing=True)
    if not source or not target or source.name!=expected_source_name:
        raise ValueError('Source identity does not match')
    previous=session.get(PlayerMerge,source_id)
    if previous:
        if previous.target_id!=target.id:
            raise ValueError('Source already belongs to a different destination')
        return {'already_merged':True,'target':summary(session,target)}
    if session.scalar(select(Account).where(Account.player_id==source_id)):
        raise ValueError('Source has an independent account; refusing to discard login')
    if session.scalar(select(PlayerMerge).where(PlayerMerge.target_id==source_id)):
        raise ValueError('Merge chains are not supported')
    if session.get(PlayerMerge,target.id):
        raise ValueError('Destination is itself a merged identity')
    # Lock all games in the same order as star/memo writes.
    games=list(session.scalars(select(Game).where(Game.player_id.in_([source.id,target.id])).order_by(Game.id)))
    for game in games:
        session.execute(update(Game).where(Game.id==game.id).values(move_revision=Game.move_revision))
        session.refresh(game)
    clears=list(session.scalars(select(Clear).where(Clear.player_id.in_([source.id,target.id]))))
    def snapshot(row):
        return {column.name:getattr(row,column.name) for column in row.__table__.columns}
    backup={'source':{'id':source.id,'name':source.name},'target':{'id':target.id,'name':target.name},
            'games':[snapshot(g) for g in games],'clears':[snapshot(c) for c in clears],
            'source_token_hash':source.token_hash}
    by_puzzle=defaultdict(list)
    for clear in clears:
        by_puzzle[clear.puzzle_id].append(clear)
    removed=[]
    for entries in by_puzzle.values():
        # One award per board; retain best earned score, then earliest clear.
        winner=max(entries,key=lambda c:(c.points,-c.cleared_at,-c.seconds,c.id))
        for clear in entries:
            if clear is not winner:
                removed.append(clear.id)
                session.delete(clear)
    session.flush()
    for clear in clears:
        if clear.id not in removed:
            clear.player_id=target.id
    for game in games:
        game.player_id=target.id
    target.name=source.name
    # The old guest device keeps working as a revocable account session.
    old_hash=source.token_hash
    session.execute(update(LoginSession).where(LoginSession.player_id==source.id).values(player_id=target.id))
    legacy=session.get(LoginSession,old_hash)
    if not legacy:
        session.add(LoginSession(token_hash=old_hash,player_id=target.id,expires_at=time.time()+30*86400))
    source.token_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    session.flush()
    # Preserve all games/moves/memos, select one current game per difficulty.
    active=defaultdict(list)
    for game in games:
        if game.active:
            active[session.get(Puzzle,game.puzzle_id).difficulty].append(game)
    cleared=set(by_puzzle)
    for entries in active.values():
        def priority(game):
            correct=session.scalar(select(func.count(Move.id)).where(Move.game_id==game.id,Move.correct.is_(True)))
            memo=session.get(GameMemo,game.id)
            return (game.finished_at is None and game.puzzle_id not in cleared,
                    correct,sum(v!=0 for v in memo.cells) if memo else 0,-game.mistakes,game.started_at)
        keep=max(entries,key=priority)
        for game in entries:
            game.active=game is keep
    session.add(PlayerMerge(source_id=source.id,target_id=target.id,backup=backup))
    session.flush()
    return {'already_merged':False,'removed_duplicate_clears':len(removed),'target':summary(session,target)}
