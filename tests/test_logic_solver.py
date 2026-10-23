import random

import pytest

from logic_solver import logical_result, _logical_result
from puzzle_engine import LEVELS, InvalidPuzzle, checked_solution, certify_generated, fingerprint, generate

# Unique and connected, but the supported non-trial deductions stall.
STALLED = [
    [1,1,5,8,8,8,8,0,0], [1,5,5,8,8,8,8,0,0],
    [5,5,5,5,8,8,0,0,0], [4,4,4,5,5,0,0,2,2],
    [4,7,4,6,6,0,0,2,2], [7,7,7,6,7,3,3,2,2],
    [7,7,7,7,7,3,3,3,2], [7,7,7,7,3,3,7,3,2],
    [7,7,7,7,7,7,7,3,3],
]


def test_unique_existing_board_remains_valid_but_is_not_generated():
    answer = checked_solution(STALLED)
    assert answer == [1,5,7,4,0,3,6,8,2]
    assert not logical_result(STALLED).solved
    puzzle = dict(size=9, difficulty='expert', points=100, regions=STALLED,
                  solution=answer, fingerprint=fingerprint(STALLED))
    with pytest.raises(InvalidPuzzle, match='non-trial'):
        certify_generated(puzzle)


@pytest.mark.parametrize('level', LEVELS)
def test_generated_boards_solve_without_search(level, monkeypatch):
    puzzles = [generate(level, random.Random(seed)) for seed in range(8)]
    # The deduction pass uses only regions, never saved answers or search.
    def forbidden(*args, **kwargs):
        raise AssertionError('Search called by deduction pass')
    monkeypatch.setattr('puzzle_engine.solutions', forbidden)
    _logical_result.cache_clear()
    for puzzle in puzzles:
        result = logical_result(puzzle['regions'])
        assert result.solved
        assert list(result.columns) == puzzle['solution']
