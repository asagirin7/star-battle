import random

import pytest

from hint_engine import next_hint
from puzzle_engine import generate


def test_star_exclusions_are_free_and_have_new_targets():
    regions = [[r]*4 for r in range(4)]
    hint = next_hint(regions, [(0, 1)])
    assert hint['points'] == 0
    assert hint['action'] == 'cross'
    assert [0, 1] not in hint['target_cells']
    assert [1, 2] in hint['target_cells']
    crossed = [r*4+c for r,c in hint['target_cells']]
    second = next_hint(regions, [(0, 1)], crossed)
    assert second['points'] == 1
    assert second['target_cells'] == [[1, 3]]


def test_single_and_finished_board():
    regions = [[r]*4 for r in range(4)]
    assert next_hint(regions, crosses=[0, 2, 3])['target_cells'] == [[0, 1]]
    stars = [(0,1), (1,3), (2,0), (3,2)]
    crosses = [p for p in range(16) if divmod(p,4) not in stars]
    assert next_hint(regions, stars, crosses) is None


@pytest.mark.parametrize('stars,crosses', [([(0,0),(1,1)], []), ([(0,0)], [0]), ([], [0,1,2,3]), ([(4,0)], []), ([], [-1])])
def test_invalid_or_contradictory_state(stars, crosses):
    with pytest.raises(ValueError):
        next_hint([[r]*4 for r in range(4)], stars, crosses)


@pytest.mark.parametrize('transform', [lambda r,c,n:(r,c), lambda r,c,n:(c,n-1-r), lambda r,c,n:(r,n-1-c)])
def test_deductions_stay_sound_under_rotation_and_reflection(transform, monkeypatch):
    puzzle = generate('easy', random.Random(17))
    original = puzzle['regions']
    n = len(original)
    regions = [[None]*n for _ in range(n)]
    for r in range(n):
        for c in range(n):
            rr,cc = transform(r,c,n)
            regions[rr][cc] = original[r][c]
    answer = {transform(r,c,n) for r,c in enumerate(puzzle['solution'])}
    # No search may run while deductions are evaluated.
    monkeypatch.setattr('puzzle_engine.solutions', lambda *a, **kw: pytest.fail('hint searched'))
    stars, crosses = set(), set()
    for _ in range(n*n*2):
        hint = next_hint(regions, stars, crosses)
        if hint is None:
            break
        assert hint['explanation'] and hint['source_cells'] and hint['target_cells']
        targets = {tuple(p) for p in hint['target_cells']}
        if hint['action'] == 'star':
            assert targets <= answer
            assert not targets & stars
            stars |= targets
        else:
            assert not targets & answer
            indexes = {r*n+c for r,c in targets}
            assert not indexes & crosses
            crosses |= indexes
    assert stars == answer


@pytest.mark.parametrize('regions,crosses,technique,points', [
    ([[3,3,3,0,0,0],[3,3,3,0,2,0],[3,3,3,3,2,2],[3,4,4,4,2,2],[3,4,4,2,2,1],[4,4,5,5,5,1]], [0,9,21,23,27,31,34], 'region_to_line', 2),
    ([[1,1,1,1,1,2],[1,1,1,2,2,2],[1,1,1,2,3,3],[5,5,5,5,0,3],[5,5,0,0,0,4],[5,5,0,4,4,4]], [2,7,10,20,21,28,30,31,32], 'line_to_region', 4),
    ([[1,1,1,1,1,2],[1,1,1,2,2,2],[1,1,1,2,3,3],[5,5,5,5,0,3],[5,5,0,0,0,4],[5,5,0,4,4,4]], [3,19,21,22,35], 'n_to_n', 5),
])
def test_cheapest_technique_and_current_scoring(regions, crosses, technique, points):
    hint = next_hint(regions, crosses=crosses)
    assert (hint['technique'], hint['points']) == (technique, points)
    from puzzle_engine import checked_solution
    n = len(regions)
    answer = {(r,c) for r,c in enumerate(checked_solution(regions))}
    assert not {tuple(p) for p in hint['target_cells']} & answer
    # Targets already crossed do not repeatedly consume a hint.
    augmented = crosses + [r*n+c for r,c in hint['target_cells']]
    following = next_hint(regions, crosses=augmented)
    assert following is None or following['target_cells'] != hint['target_cells']


def test_shape_uses_ten_point_base_and_explains_its_candidates():
    regions = [[5,1,1,1,1,1,0,0],[1,1,1,1,1,2,0,0],[1,1,1,1,1,2,0,0],[1,1,1,1,1,0,0,0],[4,4,3,1,1,1,7,7],[4,4,3,1,1,7,7,7],[4,4,4,6,7,7,7,7],[4,4,4,4,4,4,7,7]]
    stars = [[0,0],[6,3],[4,2],[7,1]]
    crosses = [1,2,3,4,5,6,7,8,9,16,24,32,40,48,56,11,19,27,35,42,43,44,49,50,52,53,54,55,58,59,60,10,18,25,26,33,36,37,38,39,41,29,45,61,17,62,63]
    hint = next_hint(regions, stars, crosses)
    assert hint['technique'] == 'shape_exclusion'
    source = hint['source_cells']
    rows = {r for r,c in source}
    cols = {c for r,c in source}
    assert hint['points'] == 10 + max(rows)-min(rows)+1-len(rows) + max(cols)-min(cols)+1-len(cols)
    assert hint['points'] >= 10
