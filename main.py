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
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import database_url
from models import Clear, Game, Move, Player, Puzzle
from puzzle_engine import generate, multiplier, life_limit, clear_points

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
    p = session.scalar(select(Player).where(Player.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    if not p:
        raise HTTPException(401, 'プレイヤーを登録してください。')
    return p


class Profile(BaseModel):
    name: str = Field(min_length=1, max_length=24)


class Start(BaseModel):
    difficulty: Literal['easy', 'medium', 'hard', 'expert'] = 'easy'
    request_id: uuid.UUID


class StarAttempt(BaseModel):
    row: int = Field(ge=0, le=8, strict=True)
    col: int = Field(ge=0, le=8, strict=True)
    request_id: uuid.UUID


def stats(session, p):
    points, count = session.execute(select(func.coalesce(func.sum(Clear.points), 0), func.count(Clear.id)).where(Clear.player_id == p.id)).one()
    return dict(id=p.id, name=p.name, points=points, clears=count)


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


@app.get('/api/me')
def me(p: Player = Depends(player), session: Session = Depends(db)):
    return stats(session, p)


def puzzle_view(puzzle):
    return dict(id=puzzle.id, size=puzzle.size, difficulty=puzzle.difficulty,
                points=clear_points(puzzle.size, 0), multiplier=multiplier(puzzle.size),
                initial_lives=life_limit(puzzle.size), scoring='fixed' if puzzle.size == 9 else 'lives', regions=puzzle.regions)


def game_view(session, game):
    puzzle = session.get(Puzzle, game.puzzle_id)
    stars = set((m.row, m.col) for m in session.scalars(
        select(Move).where(Move.game_id == game.id, Move.correct.is_(True))))
    clear = session.scalar(select(Clear).where(Clear.game_id == game.id))
    return dict(id=game.id, started_at=game.started_at, puzzle=puzzle_view(puzzle),
                stars=sorted(stars), mistakes=game.mistakes,
                lives=max(0, life_limit(puzzle.size)-game.mistakes),
                completed=clear is not None, score=clear.points if clear else 0,
                seconds=(clear.seconds if clear else max(0, int((game.finished_at or time.time())-game.started_at))),
                game_over=game.mistakes >= life_limit(puzzle.size))


@app.get('/api/games/current')
def current(difficulty: Literal['easy', 'medium', 'hard', 'expert'] = 'easy',
            p: Player = Depends(player), session: Session = Depends(db)):
    game = session.scalar(select(Game).join(Puzzle, Puzzle.id == Game.puzzle_id)
                          .where(Game.player_id == p.id, Game.active.is_(True),
                                 Puzzle.difficulty == difficulty)
                          .order_by(Game.started_at.desc()))
    return game_view(session, game) if game else None


@app.get('/api/games/{game_id}')
def get_game(game_id: str, p: Player = Depends(player), session: Session = Depends(db)):
    game = owned_game(session, game_id, p.id)
    return game_view(session, game)


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
        return game_view(session, existing)
    for _ in range(5):
        try:
            generated = generate(body.difficulty)
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
    correct = puzzle.solution[body.row] == body.col
    if not previous and not state['completed'] and not state['game_over']:
        session.add(Move(game_id=game.id, request_id=str(body.request_id),
                         row=body.row, col=body.col, correct=correct))
        if not correct:
            game.mistakes += 1
            if game.mistakes >= life_limit(puzzle.size):
                game.finished_at = time.time()
        session.flush()
        stars = set(map(tuple, state['stars']))
        if correct:
            stars.add((body.row, body.col))
        if len(stars) == puzzle.size:
            game.finished_at = time.time()
            session.add(Clear(player_id=p.id, puzzle_id=puzzle.id, game_id=game.id,
                              points=clear_points(puzzle.size, game.mistakes), mistakes=game.mistakes,
                              seconds=max(0, int(time.time()-game.started_at))))
    session.commit()
    return dict(correct=previous.correct if previous else correct,
                game=game_view(session, game), player=stats(session, p))


@app.get('/api/history')
def history(p: Player = Depends(player), session: Session = Depends(db)):
    rows = session.scalars(select(Clear).where(Clear.player_id == p.id).order_by(Clear.cleared_at.desc()).limit(100))
    return [dict(puzzle_id=c.puzzle_id, points=c.points, mistakes=c.mistakes, seconds=c.seconds,
                 difficulty=(session.get(Puzzle, c.puzzle_id).difficulty if session.get(Puzzle, c.puzzle_id)
                             else c.puzzle_id.split('-')[0]), cleared_at=c.cleared_at) for c in rows]


@app.get('/api/ranking')
def ranking(session: Session = Depends(db)):
    total = func.sum(Clear.points)
    rows = session.execute(select(Player.id, Player.name, total.label('points'), func.count(Clear.id).label('clears'))
                           .join(Clear).group_by(Player.id, Player.name)
                           .order_by(total.desc(), func.count(Clear.id).desc(), Player.id).limit(100))
    return [dict(row._mapping) for row in rows]


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
