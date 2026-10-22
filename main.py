import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import database_url
from models import Clear, Game, Player

ROOT = Path(__file__).resolve().parent
PUZZLES = {p['id']: p for p in json.loads((ROOT / 'puzzles.json').read_text())}
engine = create_engine(database_url(), pool_pre_ping=True)
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
    puzzle_id: str


class Finish(BaseModel):
    stars: list[tuple[int, int]] = Field(max_length=8)


def stats(session, p):
    points, count = session.execute(select(func.coalesce(func.sum(Clear.points), 0), func.count(Clear.id)).where(Clear.player_id == p.id)).one()
    return dict(id=p.id, name=p.name, points=points, clears=count)


@app.get('/')
def index():
    return FileResponse(ROOT / 'static/index.html')


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


@app.get('/api/puzzles')
def puzzles(p: Player = Depends(player), session: Session = Depends(db)):
    cleared = set(session.scalars(select(Clear.puzzle_id).where(Clear.player_id == p.id)))
    return [dict(**puzzle, cleared=puzzle['id'] in cleared) for puzzle in PUZZLES.values()]


@app.post('/api/games')
def start(body: Start, p: Player = Depends(player), session: Session = Depends(db)):
    if body.puzzle_id not in PUZZLES:
        raise HTTPException(404, '問題が見つかりません。')
    # Reuse an attempt on reload rather than creating unlimited abandoned games.
    game = session.scalar(select(Game).where(Game.player_id == p.id, Game.puzzle_id == body.puzzle_id).order_by(Game.started_at.desc()))
    if not game:
        game = Game(player_id=p.id, puzzle_id=body.puzzle_id)
        session.add(game)
        session.commit()
    return dict(id=game.id, started_at=game.started_at)


def valid_stars(puzzle, stars):
    n = puzzle['size']
    if len(stars) != n or len(set(stars)) != n:
        return False
    if any(not (0 <= r < n and 0 <= c < n) for r,c in stars):
        return False
    if any(len({f(r,c) for r,c in stars}) != n for f in
           [lambda r,c:r, lambda r,c:c, lambda r,c:puzzle['regions'][r][c]]):
        return False
    return all(max(abs(r-rr),abs(c-cc)) > 1 for i,(r,c) in enumerate(stars) for rr,cc in stars[i+1:])


@app.post('/api/games/{game_id}/complete')
def complete(game_id: str, body: Finish, p: Player = Depends(player), session: Session = Depends(db)):
    game = session.get(Game, game_id)
    if not game or game.player_id != p.id:
        raise HTTPException(404, 'ゲームが見つかりません。')
    puzzle = PUZZLES[game.puzzle_id]
    if not valid_stars(puzzle, body.stars):
        raise HTTPException(422, '星の配置を見直してください。')
    existing = session.scalar(select(Clear).where(Clear.player_id == p.id, Clear.puzzle_id == game.puzzle_id))
    awarded = 0
    if not existing:
        session.add(Clear(player_id=p.id, puzzle_id=game.puzzle_id, game_id=game.id,
                          points=puzzle['points'], seconds=max(0, int(time.time()-game.started_at))))
        try:
            session.commit()
            awarded = puzzle['points']
        except IntegrityError:
            session.rollback()  # Another tab completed the same puzzle concurrently.
    return dict(awarded=awarded, player=stats(session, p))


@app.get('/api/history')
def history(p: Player = Depends(player), session: Session = Depends(db)):
    rows = session.scalars(select(Clear).where(Clear.player_id == p.id).order_by(Clear.cleared_at.desc()).limit(100))
    return [dict(puzzle_id=c.puzzle_id, points=c.points, seconds=c.seconds, cleared_at=c.cleared_at) for c in rows]


@app.get('/api/ranking')
def ranking(session: Session = Depends(db)):
    total = func.sum(Clear.points)
    rows = session.execute(select(Player.id, Player.name, total.label('points'), func.count(Clear.id).label('clears'))
                           .join(Clear).group_by(Player.id, Player.name)
                           .order_by(total.desc(), func.count(Clear.id).desc(), Player.id).limit(100))
    return [dict(row._mapping) for row in rows]


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
