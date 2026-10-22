import time
import uuid
from sqlalchemy import Float, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = 'players'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(24))


class Game(Base):
    __tablename__ = 'games'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    player_id: Mapped[str] = mapped_column(ForeignKey('players.id'), index=True)
    puzzle_id: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[float] = mapped_column(Float, default=time.time)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    mistakes: Mapped[int] = mapped_column(default=0, server_default='0')
    active: Mapped[bool] = mapped_column(default=True, server_default='true')
    move_revision: Mapped[int] = mapped_column(default=0, server_default='0')


class Clear(Base):
    __tablename__ = 'clears'
    __table_args__ = (UniqueConstraint('player_id', 'puzzle_id', name='uq_player_puzzle'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    player_id: Mapped[str] = mapped_column(ForeignKey('players.id'), index=True)
    puzzle_id: Mapped[str] = mapped_column(String(32))
    game_id: Mapped[str] = mapped_column(ForeignKey('games.id'), unique=True)
    points: Mapped[int]
    mistakes: Mapped[int] = mapped_column(default=0, server_default='0')
    seconds: Mapped[int]
    cleared_at: Mapped[float] = mapped_column(Float, default=time.time)


class Puzzle(Base):
    __tablename__ = 'puzzles'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    difficulty: Mapped[str] = mapped_column(String(16))
    size: Mapped[int]
    points: Mapped[int]
    regions: Mapped[list] = mapped_column(JSON)
    solution: Mapped[list] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)


class Move(Base):
    __tablename__ = 'moves'
    __table_args__ = (UniqueConstraint('game_id', 'request_id', name='uq_game_request'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    game_id: Mapped[str] = mapped_column(ForeignKey('games.id'), index=True)
    request_id: Mapped[str] = mapped_column(String(36))
    row: Mapped[int]
    col: Mapped[int]
    correct: Mapped[bool]
