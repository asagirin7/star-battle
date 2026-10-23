"""Current win streaks derived from durable clear and failed-game records.

Legacy IDs such as easy-01 encode their difficulty. Unknown terminal history
is a conservative boundary for every difficulty: continuity before it cannot
be established. Equal-time failures take precedence over clears.
"""
from sqlalchemy import case, func, or_, select

from models import Clear, Game, Puzzle
from puzzle_engine import LEVELS, life_limit


def _difficulty(puzzle_id):
    return case(
        (Puzzle.difficulty.in_(tuple(LEVELS)), Puzzle.difficulty),
        *[(puzzle_id.startswith(level + '-', autoescape=True), level) for level in LEVELS],
        else_=None,
    )


def derive_streaks(session, player_id):
    """Count unique cleared puzzles after the latest failure in each mode.

    Clears already have a player/puzzle uniqueness constraint, so resumed
    games and retries cannot count twice. Points intentionally do not matter.
    No known completion timestamp means no event; old unfinished rows must
    never be guessed to be failures.
    """
    game_level = _difficulty(Game.puzzle_id)
    clear_level = _difficulty(Clear.puzzle_id)
    failures = dict(session.execute(
        select(game_level, func.max(Game.finished_at))
        .outerjoin(Puzzle, Puzzle.id == Game.puzzle_id)
        .where(Game.player_id == player_id, Game.finished_at.is_not(None),
               Game.mistakes >= case(
                   *[(game_level == level, life_limit(size))
                     for level, (size, _) in LEVELS.items()], else_=1))
        .group_by(game_level)
    ).all())
    unknown_clear = session.scalar(
        select(func.max(Clear.cleared_at))
        .outerjoin(Puzzle, Puzzle.id == Clear.puzzle_id)
        .where(Clear.player_id == player_id, clear_level.is_(None))
    )
    unknown_boundary = max((value for value in
                            (failures.pop(None, None), unknown_clear)
                            if value is not None), default=None)
    conditions = []
    for level in LEVELS:
        boundary = max((value for value in (failures.get(level), unknown_boundary)
                        if value is not None), default=None)
        condition = clear_level == level
        if boundary is not None:
            condition = condition & (Clear.cleared_at > boundary)
        conditions.append(condition)
    counts = session.execute(
        select(clear_level, func.count(Clear.id))
        .outerjoin(Puzzle, Puzzle.id == Clear.puzzle_id)
        .where(Clear.player_id == player_id, or_(*conditions))
        .group_by(clear_level)
    ).all()
    return {**dict.fromkeys(LEVELS, 0), **dict(counts)}
