import hashlib
import os
import secrets
import time
import uuid
from typing import Literal
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import database_url
from models import Account, Clear, Game, GameMemo, LoginSession, Move, Player, Puzzle
from authentication import DUMMY_HASH, issue_session, password_hash, password_matches, throttle
from puzzle_engine import (
    LEVELS, InvalidPuzzle, certify_generated, checked_solution, clear_points,
    generate, life_limit, multiplier, needs_seed, seed_expert, valid_stars,
)

ROOT = Path(__file__).resolve().parent
ASSETS = ('style.css', 'board-input.js', 'app.js')
ASSET_VERSION = hashlib.sha256(b''.join((ROOT / 'static' / name).read_bytes() for name in ASSETS)).hexdigest()[:16]
INDEX_HTML = (ROOT / 'static/index.html').read_text()
for asset in ASSETS:
    INDEX_HTML = INDEX_HTML.replace(f'/static/{asset}', f'/static/{asset}?v={ASSET_VERSION}')
# The free database allows 5 connections; leave room for migrations and administration.
engine = create_engine(database_url(), pool_pre_ping=True, pool_size=3, max_overflow=0)
app = FastAPI(title='Star Battle', docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')


@app.middleware('http')
async def security(request: Request, call_next):
    if request.method in {'POST', 'PUT', 'DELETE', 'PATCH'}:
        origin = request.headers.get('origin')
        if origin and urlparse(origin).netloc != request.headers.get('host'):
            return Response(status_code=403)
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            return Response(status_code=415)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    elif request.url.path == '/' or request.url.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-cache, must-revalidate'
    return response


def db():
    with Session(engine) as session:
        yield session


def player(request: Request, session: Session = Depends(db)):
    token = request.cookies.get('star_player', '')
    digest = hashlib.sha256(token.encode()).hexdigest()
    login = session.get(LoginSession, digest)
    p = session.get(Player, login.player_id) if login and login.expires_at > time.time() else None
    if not p:
        p = session.scalar(select(Player).where(Player.token_hash == digest))
    if not p:
        raise HTTPException(401, 'プレイヤーを登録してください。')
    return p


class Profile(BaseModel):
    name: str = Field(min_length=1, max_length=24)


class Start(BaseModel):
    difficulty: Literal['easy', 'medium', 'hard', 'expert', 'expert_relaxed'] = 'easy'
    request_id: uuid.UUID
    puzzle_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')


class StarAttempt(BaseModel):
    row: int = Field(ge=0, le=8, strict=True)
    col: int = Field(ge=0, le=8, strict=True)
    request_id: uuid.UUID


def stats(session, p):
    points, count = session.execute(select(func.coalesce(func.sum(Clear.points), 0), func.count(Clear.id)).where(Clear.player_id == p.id)).one()
    account = session.scalar(select(Account).where(Account.player_id == p.id))
    return dict(id=p.id, name=p.name, points=points, clears=count,
                username=account.username if account else None)


@app.get('/')
def index():
    return HTMLResponse(INDEX_HTML)


@app.get('/health')
def health(session: Session = Depends(db)):
    session.execute(select(1))
    return {'status': 'ok'}


@app.post('/api/profile')
def profile(body: Profile, request: Request, response: Response, session: Session = Depends(db)):
    name = body.name.strip()
    if not name or any(ord(c) < 32 for c in name):
        raise HTTPException(422, '名前を1〜24文字で入力してください。')
    try:
        p = player(request, session)
        p.name = name
    except HTTPException:
        token = secrets.token_urlsafe(32)
        p = Player(name=name, token_hash=hashlib.sha256(token.encode()).hexdigest())
        session.add(p)
        response.set_cookie('star_player', token, max_age=31536000, httponly=True,
                            secure=os.getenv('COOKIE_SECURE', 'false').lower() == 'true', samesite='strict')
    session.commit()
    return stats(session, p)


class Credentials(BaseModel):
    username: str = Field(pattern=r'^[A-Za-z0-9_]{3,32}$')
    password: str = Field(min_length=10, max_length=128)


@app.post('/api/account/register')
def register_account(body: Credentials, request: Request, response: Response,
                     p: Player = Depends(player), session: Session = Depends(db)):
    throttle(session, 'register', request.client.host if request.client else 'unknown', 10)
    if session.scalar(select(Account).where(Account.player_id==p.id)):
        raise HTTPException(409, 'このプレイヤーは登録済みです。')
    session.add(Account(username=body.username.lower(), player_id=p.id, password_hash=password_hash(body.password)))
    # Retire the guest bearer token when upgrading to an account.
    p.token_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    try:
        issue_session(session, response, p.id)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, 'このログインIDは使用されています。')
    return stats(session, p)


@app.post('/api/account/login')
def login_account(body: Credentials, request: Request, response: Response, session: Session = Depends(db)):
    throttle(session, 'login-ip', request.client.host if request.client else 'unknown', 100)
    throttle(session, 'login-id', body.username.lower(), 10)
    account = session.scalar(select(Account).where(Account.username==body.username.lower()).with_for_update())
    matches = password_matches(body.password, account.password_hash if account else DUMMY_HASH)
    if not account or not matches:
        raise HTTPException(401, 'ログインIDまたはパスワードが違います。')
    issue_session(session, response, account.player_id)
    session.commit()
    return stats(session, session.get(Player, account.player_id))


@app.post('/api/account/logout')
def logout_account(request: Request, response: Response, session: Session = Depends(db)):
    digest = hashlib.sha256(request.cookies.get('star_player','').encode()).hexdigest()
    session.execute(delete(LoginSession).where(LoginSession.token_hash==digest))
    session.commit()
    response.delete_cookie('star_player', path='/', httponly=True, samesite='strict',
                           secure=os.getenv('COOKIE_SECURE','false').lower()=='true')
    return {'ok': True}


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=10, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


@app.post('/api/account/password')
def change_password(body: PasswordChange, response: Response, p: Player = Depends(player), session: Session = Depends(db)):
    throttle(session, 'password-change', p.id, 10)
    account = session.scalar(select(Account).where(Account.player_id==p.id).with_for_update())
    if not account or not password_matches(body.current_password, account.password_hash):
        raise HTTPException(401, '現在のパスワードが違います。')
    account.password_hash = password_hash(body.new_password)
    session.execute(delete(LoginSession).where(LoginSession.player_id==p.id))
    issue_session(session, response, p.id)
    session.commit()
    return {'ok': True}


@app.get('/api/me')
def me(p: Player = Depends(player), session: Session = Depends(db)):
    return stats(session, p)


def puzzle_view(puzzle):
    return dict(id=puzzle.id, size=puzzle.size, difficulty=puzzle.difficulty,
                points=clear_points(puzzle.size, 0, puzzle.difficulty), multiplier=multiplier(puzzle.size),
                initial_lives=life_limit(puzzle.size), scoring='fixed' if puzzle.size == 9 else 'lives', regions=puzzle.regions)


def verify_game(session, game):
    puzzle = session.get(Puzzle,game.puzzle_id)
    try:
        canonical = checked_solution(puzzle.regions)
        if len(puzzle.regions) != puzzle.size or LEVELS[puzzle.difficulty][0] != puzzle.size:
            raise InvalidPuzzle('Mismatched board size')
    except (InvalidPuzzle,TypeError,ValueError,KeyError):
        raise HTTPException(409,detail={'code':'invalid_puzzle','message':'盤面の整合性を確認できません。新しい問題へ切り替えます。'})
    moves = list(session.scalars(select(Move).where(Move.game_id == game.id)))
    def matches(move):
        return 0 <= move.row < puzzle.size and 0 <= move.col < puzzle.size and canonical[move.row] == move.col
    if puzzle.solution != canonical or any(move.correct != matches(move) for move in moves):
        # Use the same lock order as star placement; a concurrent resume must
        # not refund the same rejected correct move twice or overwrite a move.
        session.execute(update(Game).where(Game.id == game.id).values(move_revision=Game.move_revision+1))
        session.refresh(game)
        moves = list(session.scalars(select(Move).where(Move.game_id == game.id)
                                     .execution_options(populate_existing=True)))
        puzzle.solution = canonical
        for move in moves:
            correct = matches(move)
            if move.correct and not correct:
                move.correct = False
            elif not move.correct and correct:
                move.correct = True
                game.mistakes = max(0,game.mistakes-1)
                if game.mistakes < life_limit(puzzle.size):
                    game.finished_at = None
    session.flush()
    return puzzle,moves


def game_view(session, game):
    puzzle,moves = verify_game(session,game)
    stars = {(m.row,m.col) for m in moves if m.correct}
    clear = session.scalar(select(Clear).where(Clear.game_id == game.id))
    memo = session.get(GameMemo, game.id)
    return dict(id=game.id, started_at=game.started_at, puzzle=puzzle_view(puzzle),
                memos=memo.cells if memo else None, memo_revision=memo.revision if memo else 0,
                stars=sorted(stars), mistakes=game.mistakes,
                lives=max(0, life_limit(puzzle.size)-game.mistakes),
                completed=clear is not None, score=clear.points if clear else 0,
                seconds=(clear.seconds if clear else max(0, int((game.finished_at or time.time())-game.started_at))),
                game_over=game.mistakes >= life_limit(puzzle.size))


@app.get('/api/games/current')
def current(difficulty: Literal['easy', 'medium', 'hard', 'expert', 'expert_relaxed'] = 'easy',
            p: Player = Depends(player), session: Session = Depends(db)):
    game = session.scalar(select(Game).join(Puzzle, Puzzle.id == Game.puzzle_id)
                          .where(Game.player_id == p.id, Game.active.is_(True),
                                 Puzzle.difficulty == difficulty)
                          .order_by(Game.started_at.desc()))
    if not game:
        return None
    try:
        result = game_view(session,game)
    except HTTPException as error:
        if not isinstance(error.detail,dict) or error.detail.get('code') != 'invalid_puzzle':
            raise
        game.active = False
        session.commit()
        return None
    session.commit()
    return result


@app.get('/api/account/resume')
def resume_account(p: Player = Depends(player), session: Session = Depends(db)):
    game = session.scalar(select(Game).where(Game.player_id==p.id, Game.active.is_(True))
                          .order_by(Game.started_at.desc()))
    if not game:
        return None
    try:
        result = game_view(session, game)
    except HTTPException as error:
        if not isinstance(error.detail, dict) or error.detail.get('code')!='invalid_puzzle':
            raise
        game.active = False
        session.commit()
        return None
    session.commit()
    return result


@app.get('/api/games/{game_id}')
def get_game(game_id: str, p: Player = Depends(player), session: Session = Depends(db)):
    game = owned_game(session, game_id, p.id)
    result = game_view(session,game)
    session.commit()
    return result


def owned_game(session, game_id, player_id):
    game = session.get(Game, game_id)
    if not game or game.player_id != player_id or not session.get(Puzzle, game.puzzle_id):
        raise HTTPException(404, 'ゲームが見つかりません。')
    return game


@app.post('/api/games')
def start(body: Start, p: Player = Depends(player), session: Session = Depends(db)):
    game_id = str(body.request_id)
    existing = session.get(Game, game_id)
    if existing:
        if existing.player_id != p.id:
            raise HTTPException(404, 'ゲームが見つかりません。')
        result = game_view(session,existing)
        session.commit()
        return result
    if body.puzzle_id:
        puzzle = session.get(Puzzle, body.puzzle_id)
        if not puzzle:
            raise HTTPException(404, '共有された問題が見つかりません。')
        try:
            checked_solution(puzzle.regions)
        except InvalidPuzzle:
            raise HTTPException(404, 'この問題は現在共有できません。')
        # Player row serializes opening the same shared puzzle on two devices.
        session.execute(update(Player).where(Player.id==p.id).values(name=Player.name))
        existing = session.scalar(select(Game).where(Game.player_id==p.id, Game.puzzle_id==puzzle.id)
                                  .order_by(Game.started_at.desc()))
        session.execute(update(Game).where(Game.player_id==p.id, Game.puzzle_id.in_(
            select(Puzzle.id).where(Puzzle.difficulty==puzzle.difficulty))).values(active=False))
        if existing:
            existing.active = True
            result = game_view(session, existing)
            session.commit()
            return result
        game = Game(id=game_id, player_id=p.id, puzzle_id=puzzle.id)
        session.add(game)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.get(Game, game_id)
            if existing and existing.player_id==p.id:
                return game_view(session,existing)
            raise HTTPException(409, 'もう一度問題を開いてください。')
        return game_view(session, game)
    if body.difficulty in {'expert','expert_relaxed'} and needs_seed(body.difficulty):
        stored = session.scalars(select(Puzzle).where(Puzzle.difficulty == body.difficulty)
                                 .order_by(func.random()).limit(12))
        for item in stored:
            seed_expert(dict(size=item.size, difficulty=item.difficulty, regions=item.regions, solution=item.solution))
    for _ in range(5):
        try:
            generated = certify_generated(generate(body.difficulty))
            if generated['difficulty'] != body.difficulty:
                raise InvalidPuzzle('Mismatched difficulty')
        except InvalidPuzzle:
            continue
        except TimeoutError:
            raise HTTPException(503, '問題の生成に時間がかかっています。もう一度お試しください。')
        if not session.scalar(select(Puzzle.id).where(Puzzle.fingerprint == generated['fingerprint'])):
            break
    else:
        raise HTTPException(503, '新しい問題を作り直してください。')
    puzzle = Puzzle(id=uuid.uuid4().hex, **generated)
    game = Game(id=game_id, player_id=p.id, puzzle_id=puzzle.id)
    # One current board per difficulty; completed and failed boards stay visible until Next.
    previous = list(session.scalars(select(Game.id).join(Puzzle, Puzzle.id == Game.puzzle_id)
                                   .where(Game.player_id == p.id, Game.active.is_(True), Puzzle.difficulty == body.difficulty)))
    if previous:
        session.execute(update(Game).where(Game.id.in_(previous)).values(active=False))
    try:
        session.add(puzzle)
        session.flush()
        session.add(game)
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.get(Game, game_id)
        if existing and existing.player_id == p.id:
            return game_view(session, existing)
        raise HTTPException(409, 'もう一度、新しい問題を作成してください。')
    return game_view(session, game)


@app.get('/api/puzzles/{puzzle_id}')
def shared_puzzle(puzzle_id: str, session: Session = Depends(db)):
    puzzle = session.get(Puzzle, puzzle_id)
    if not puzzle:
        raise HTTPException(404, '共有された問題が見つかりません。')
    try:
        checked_solution(puzzle.regions)
    except InvalidPuzzle:
        raise HTTPException(404, 'この問題は現在共有できません。')
    return puzzle_view(puzzle)


class MemoPatch(BaseModel):
    changes: dict[int, Literal[0, 2, 3]] = Field(max_length=81)


@app.post('/api/games/{game_id}/memos')
def patch_memos(game_id: str, body: MemoPatch, p: Player = Depends(player), session: Session = Depends(db)):
    game = owned_game(session, game_id, p.id)
    puzzle = session.get(Puzzle, game.puzzle_id)
    if any(i < 0 or i >= puzzle.size**2 for i in body.changes):
        raise HTTPException(422, '盤面の範囲外です。')
    # Merge cell edits under the same lock as stars; other-device edits survive.
    session.execute(update(Game).where(Game.id==game.id).values(move_revision=Game.move_revision+1))
    memo = session.get(GameMemo, game.id, populate_existing=True)
    if not memo:
        memo = GameMemo(game_id=game.id, cells=[0]*(puzzle.size**2), revision=0)
        session.add(memo)
    values = memo.cells[:]
    for i,value in body.changes.items():
        values[i] = value
    memo.cells = values
    memo.revision += 1
    session.commit()
    return {'memos': memo.cells, 'memo_revision': memo.revision}


@app.post('/api/games/{game_id}/stars')
def place_star(game_id: str, body: StarAttempt, p: Player = Depends(player), session: Session = Depends(db)):
    game = owned_game(session, game_id, p.id)
    puzzle = session.get(Puzzle, game.puzzle_id)
    if body.row >= puzzle.size or body.col >= puzzle.size:
        raise HTTPException(422, '盤面の範囲外です。')
    # The UPDATE serializes mutations on PostgreSQL and SQLite, including concurrent retries.
    session.execute(update(Game).where(Game.id == game.id).values(move_revision=Game.move_revision+1))
    session.refresh(game)
    previous = session.scalar(select(Move).where(Move.game_id == game.id,
                                                 Move.request_id == str(body.request_id)))
    if previous and (previous.row != body.row or previous.col != body.col):
        session.rollback()
        raise HTTPException(409, '同じ操作IDを別のマスに使うことはできません。')
    state = game_view(session, game)
    stars = set(map(tuple,state['stars']))
    correct = puzzle.solution[body.row] == body.col and valid_stars(puzzle.regions,stars | {(body.row,body.col)})
    if not previous and not state['completed'] and not state['game_over']:
        session.add(Move(game_id=game.id, request_id=str(body.request_id),
                         row=body.row, col=body.col, correct=correct))
        if not correct:
            game.mistakes += 1
            if game.mistakes >= life_limit(puzzle.size):
                game.finished_at = time.time()
        session.flush()
        if correct:
            stars.add((body.row, body.col))
        if valid_stars(puzzle.regions,stars,complete=True):
            game.finished_at = time.time()
            session.add(Clear(player_id=p.id, puzzle_id=puzzle.id, game_id=game.id,
                              points=clear_points(puzzle.size, game.mistakes, puzzle.difficulty), mistakes=game.mistakes,
                              seconds=max(0, int(time.time()-game.started_at))))
    session.commit()
    return dict(correct=bool(previous.correct and correct) if previous else correct,
                game=game_view(session, game), player=stats(session, p))


@app.get('/api/history')
def history(p: Player = Depends(player), session: Session = Depends(db)):
    rows = session.scalars(select(Clear).where(Clear.player_id == p.id).order_by(Clear.cleared_at.desc()).limit(100))
    return [dict(puzzle_id=c.puzzle_id, points=c.points, mistakes=c.mistakes, seconds=c.seconds,
                 difficulty=(session.get(Puzzle, c.puzzle_id).difficulty if session.get(Puzzle, c.puzzle_id)
                             else c.puzzle_id.split('-')[0]), cleared_at=c.cleared_at) for c in rows]


@app.get('/api/ranking')
def ranking(period: Literal['all', 'daily'] = 'all', session: Session = Depends(db)):
    total = func.sum(Clear.points)
    query = select(Player.id, Player.name, total.label('points'), func.count(Clear.id).label('clears')).join(Clear)
    if period == 'daily':
        # Japan standard time has a fixed UTC+9 offset. Filter by completion time.
        start = ((int(time.time())+9*3600)//86400)*86400-9*3600
        query = query.where(Clear.cleared_at >= start, Clear.cleared_at < start+86400)
    rows = session.execute(query.group_by(Player.id, Player.name)
                           .order_by(total.desc(), func.count(Clear.id).desc(), Player.id).limit(100))
    return [dict(row._mapping) for row in rows]


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
