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
        assert db.execute('SELECT points,mistakes FROM clears').fetchall()==[(3,0)]*3
        assert db.execute('SELECT mistakes FROM games').fetchall()==[(0,)]*3
        assert db.execute('SELECT count(*) FROM puzzles').fetchone()[0]==0
    alembic('upgrade','head')
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT sum(points) FROM clears').fetchone()[0]==9
