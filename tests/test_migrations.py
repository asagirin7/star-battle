"""Existing players and history survive the switch to remaining-life scores."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def test_legacy_history_migrates_to_three_lives(tmp_path):
    path=tmp_path/'upgrade.db'
    env={**os.environ,'DATABASE_URL':f'sqlite:///{path}'}
    def alembic(*args):
        subprocess.run([sys.executable,'-m','alembic',*args],env=env,cwd=ROOT,check=True,capture_output=True)
    alembic('upgrade','001')
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO players VALUES ('player', 'hash', '以前のプレイヤー')")
        for i,(level,points) in enumerate([('easy',100),('medium',180),('hard',280)]):
            db.execute('INSERT INTO games VALUES (?, ?, ?, ?)',(f'game{i}','player',f'{level}-01',1.0))
            db.execute('INSERT INTO clears VALUES (?, ?, ?, ?, ?, ?, ?)',(f'clear{i}','player',f'{level}-01',f'game{i}',points,10,11.0))
    alembic('upgrade','head')
    alembic('check')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT name FROM players').fetchone()[0]=='以前のプレイヤー'
        assert db.execute('SELECT points,mistakes FROM clears').fetchall()==[(3,0),(6,0),(9,0)]
        assert db.execute('SELECT mistakes FROM games').fetchall()==[(0,)]*3
        assert db.execute('SELECT count(*) FROM puzzles').fetchone()[0]==0
    alembic('upgrade','head')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT sum(points) FROM clears').fetchone()[0]==18


def test_current_history_reweights_once_and_preserves_mistakes(tmp_path):
    path=tmp_path/'weighted.db'
    env={**os.environ,'DATABASE_URL':f'sqlite:///{path}'}
    def alembic(*args):
        subprocess.run([sys.executable,'-m','alembic',*args],env=env,cwd=ROOT,check=True,capture_output=True)
    alembic('upgrade','002')
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO players VALUES ('player','hash','既存プレイヤー')")
        for i,level in enumerate(['easy','medium','hard']):
            db.execute('INSERT INTO puzzles VALUES (?,?,?,?,?,?,?)',(f'p{i}',level,6+i,3,'[]','[]',str(i)*64))
            db.execute('INSERT INTO games (id,player_id,puzzle_id,started_at,mistakes) VALUES (?,?,?,?,?)',(f'g{i}','player',f'p{i}',1.0,i))
            db.execute('INSERT INTO clears (id,player_id,puzzle_id,game_id,points,seconds,cleared_at,mistakes) VALUES (?,?,?,?,?,?,?,?)',(f'c{i}','player',f'p{i}',f'g{i}',3-i,10,11.0,i))
    for _ in range(2):
        alembic('upgrade','head')
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT points,mistakes FROM clears ORDER BY id').fetchall()==[(3,0),(4,1),(3,2)]
            assert db.execute('SELECT points FROM puzzles ORDER BY id').fetchall()==[(3,),(6,),(9,)]
    alembic('downgrade','002')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT points FROM clears ORDER BY id').fetchall()==[(3,),(2,),(1,)]



def test_expert_history_changes_to_fixed_100_once(tmp_path):
    path=tmp_path/'expert.db'
    env={**os.environ,'DATABASE_URL':f'sqlite:///{path}'}
    def alembic(*args):
        subprocess.run([sys.executable,'-m','alembic',*args],env=env,cwd=ROOT,check=True,capture_output=True)
    alembic('upgrade','003')
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO players VALUES ('p','hash','9×9プレイヤー')")
        for i,(size,points,mistakes) in enumerate([(9,30,0),(9,0,1),(8,9,0)]):
            db.execute('INSERT INTO puzzles VALUES (?,?,?,?,?,?,?)',(f'p{i}','expert' if size==9 else 'hard',size,points,'[]','[]',str(i)*64))
            db.execute('INSERT INTO games (id,player_id,puzzle_id,started_at,mistakes) VALUES (?,?,?,?,?)',(f'g{i}','p',f'p{i}',1.0,mistakes))
            db.execute('INSERT INTO clears (id,player_id,puzzle_id,game_id,points,seconds,cleared_at,mistakes) VALUES (?,?,?,?,?,?,?,?)',(f'c{i}','p',f'p{i}',f'g{i}',points,10,11.0,mistakes))
    for _ in range(2):
        alembic('upgrade','head')
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT points FROM clears ORDER BY id').fetchall()==[(100,),(0,),(9,)]
            assert db.execute('SELECT points FROM puzzles ORDER BY id').fetchall()==[(100,),(100,),(9,)]
    alembic('downgrade','003')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT points FROM clears ORDER BY id').fetchall()==[(30,),(0,),(9,)]



def test_relaxed_history_changes_to_50_without_affecting_other_modes(tmp_path):
    path=tmp_path/'relaxed.db'
    env={**os.environ,'DATABASE_URL':f'sqlite:///{path}'}
    def alembic(*args):
        subprocess.run([sys.executable,'-m','alembic',*args],env=env,cwd=ROOT,check=True,capture_output=True)
    alembic('upgrade','004')
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO players VALUES ('p','hash','既存プレイヤー')")
        for i,(level,size,points,mistakes) in enumerate([('expert_relaxed',9,100,0),('expert_relaxed',9,0,1),('expert',9,100,0),('hard',8,9,0)]):
            db.execute('INSERT INTO puzzles VALUES (?,?,?,?,?,?,?)',(f'p{i}',level,size,points,'[]','[]',str(i)*64))
            db.execute('INSERT INTO games (id,player_id,puzzle_id,started_at,mistakes) VALUES (?,?,?,?,?)',(f'g{i}','p',f'p{i}',1.0,mistakes))
            db.execute('INSERT INTO clears (id,player_id,puzzle_id,game_id,points,seconds,cleared_at,mistakes) VALUES (?,?,?,?,?,?,?,?)',(f'c{i}','p',f'p{i}',f'g{i}',points,10,11.0,mistakes))
    for _ in range(2):
        alembic('upgrade','head')
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT points FROM clears ORDER BY id').fetchall()==[(50,),(0,),(100,),(9,)]
            assert db.execute('SELECT points FROM puzzles ORDER BY id').fetchall()==[(50,),(50,),(100,),(9,)]
    alembic('downgrade','004')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT points FROM clears ORDER BY id').fetchall()==[(100,),(0,),(100,),(9,)]
