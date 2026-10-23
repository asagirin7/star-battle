from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import Base, Clear, Game, Player, Puzzle
from streaks import derive_streaks


def test_streak_events_and_legacy_boundaries():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Player(id='p', token_hash='p', name='p'),
                    Player(id='other', token_hash='other', name='other')])
        def event(pid, when, *, clear=False, mistakes=0, points=1, player='p', retry=0):
            game = Game(player_id=player, puzzle_id=pid, mistakes=mistakes,
                        finished_at=when, retry_count=retry)
            db.add(game)
            db.flush()
            if clear:
                db.add(Clear(player_id=player, puzzle_id=pid, game_id=game.id,
                             cleared_at=when, points=points, seconds=1, retry_count=retry))
            db.flush()
            return game

        assert set(derive_streaks(db, 'p').values()) == {0}
        # Legacy difficulty prefixes survive missing playable puzzle records.
        event('easy-old', 1, clear=True)
        event('medium-old', 2, clear=True)
        event('hard-old', 3, clear=True)
        assert derive_streaks(db, 'p')['easy'] == 1
        event('easy-failure', 4, mistakes=3)
        assert derive_streaks(db, 'p')['easy'] == 0
        assert derive_streaks(db, 'p')['medium'] == 1
        # Partial mistakes and an unfinished failed row cannot reset a streak.
        event('medium-partial', 5, mistakes=2)
        event('medium-unfinished', None, mistakes=3)
        assert derive_streaks(db, 'p')['medium'] == 1
        # A retry clear is a win even with zero points; reopening does not add it.
        event('easy-retry', 6, clear=True, points=0, retry=1)
        event('easy-retry', None, retry=1)
        assert derive_streaks(db, 'p')['easy'] == 1
        assert derive_streaks(db, 'p')['easy'] == 1
        # Identical timestamps resolve conservatively in favor of failure.
        event('easy-tie-clear', 7, clear=True)
        event('easy-tie-failure', 7, mistakes=3)
        assert derive_streaks(db, 'p')['easy'] == 0
        event('medium-other-player', 8, mistakes=3, player='other')
        assert derive_streaks(db, 'p')['medium'] == 1
        event('unknown-id', 9, clear=True)
        assert set(derive_streaks(db, 'p').values()) == {0}
        event('medium-new', 10, clear=True)
        assert derive_streaks(db, 'p')['medium'] == 1
        event('unknown-failure', 11, mistakes=1)
        assert set(derive_streaks(db, 'p').values()) == {0}


def test_real_puzzle_difficulty_and_expert_one_life():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Player(id='p', token_hash='p', name='p'))
        for index, level in enumerate(('expert', 'expert_relaxed')):
            pid = f'opaque{index}'
            db.add(Puzzle(id=pid, difficulty=level, size=9, points=0,
                         regions=[], solution=[], fingerprint=str(index)))
            game = Game(player_id='p', puzzle_id=pid, finished_at=1)
            db.add(game)
            db.flush()
            db.add(Clear(player_id='p', puzzle_id=pid, game_id=game.id,
                         cleared_at=1, points=0, seconds=1))
        db.flush()
        assert derive_streaks(db, 'p')['expert'] == 1
        assert derive_streaks(db, 'p')['expert_relaxed'] == 1
        db.add(Game(player_id='p', puzzle_id='opaque0', finished_at=2, mistakes=1))
        db.flush()
        result = derive_streaks(db, 'p')
        assert result['expert'] == 0
        assert result['expert_relaxed'] == 1
