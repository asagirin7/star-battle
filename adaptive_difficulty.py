"""Bounded, solution-free difficulty scoring and gentle candidate weighting."""
import random
import time
from collections import OrderedDict
from hint_engine import next_hint

# Immutable region layouts, not stored solutions, identify the scoring cache.
_scores = OrderedDict()
SCORE_CACHE_LIMIT = 128
# Master-rank boards are held back until a long clear streak.
MASTER_SCORE = 90
MASTER_STREAK = 10


def allows_score(score, streak):
    return score < MASTER_SCORE or int(streak) >= MASTER_STREAK


def score_regions(regions, deadline=None):
    """Cheapest-first complete proof cost; None means stalled or out of budget.

    Interrupted proofs are not cached as stalls. This is a deterministic rule
    score, not a calibrated estimate of human solving time.
    """
    key = tuple(tuple(row) for row in regions)
    if key in _scores:
        _scores.move_to_end(key)
        return _scores[key]
    n = len(regions)
    stars, crosses, total = set(), set(), 0
    for _ in range(4*n*n):
        if len(stars) == n:
            break
        if deadline is not None and time.monotonic() >= deadline:
            return None
        try:
            hint = next_hint(regions, stars, crosses)
        except ValueError:
            return None
        if hint is None:
            total = None
            break
        targets = {tuple(p) for p in hint['target_cells']}
        before = len(stars), len(crosses)
        if hint['action'] == 'star':
            stars.update(targets)
        else:
            crosses.update(r*n+c for r, c in targets)
        if before == (len(stars), len(crosses)):
            return None
        total += hint['points']
    else:
        return None
    _scores[key] = total
    _scores.move_to_end(key)
    while len(_scores) > SCORE_CACHE_LIMIT:
        _scores.popitem(last=False)
    return total


# Each three-win step aims one rank higher: 入門 at 0, 初級 at 3, 中級 at 6,
# 上級 at 9 and 達人 from 12 wins.
TARGET_BASE = 20
TARGET_PER_WIN = 20 / 3
TARGET_MAX = 105
# The candidate nearest the target is favoured most; each next-nearest
# distance gets this fraction of the previous weight, so streaks stay soft.
DECAY = .3


def target_score(streak):
    return min(TARGET_MAX, TARGET_BASE + TARGET_PER_WIN * max(0, int(streak)))


def candidate_weights(scores, streak):
    """Tied scores have tied weights; nearer the streak target weighs more."""
    target = target_score(streak)
    distances = sorted({abs(s - target) for s in scores})
    return [DECAY ** distances.index(abs(s - target)) for s in scores]


def choose_candidate(candidates, scores, streak, rng=None):
    if not candidates or len(candidates) != len(scores):
        raise ValueError('Candidates and scores must be nonempty and aligned')
    pool = [(c, s) for c, s in zip(candidates, scores) if allows_score(s, streak)] or list(zip(candidates, scores))
    candidates, scores = [c for c, _ in pool], [s for _, s in pool]
    return (rng or random.SystemRandom()).choices(
        candidates, weights=candidate_weights(scores, streak), k=1)[0]


# No-miss clear points of a normal 9x9 board by rank.
RANK_POINTS = {'入門': 100, '初級': 150, '中級': 200, '上級': 250, '達人': 300}
UNRATED_POINTS = 100


def rank_for(score):
    return next(label for ceiling, label in [(29, '入門'), (49, '初級'),
                (69, '中級'), (MASTER_SCORE-1, '上級'), (float('inf'), '達人')] if score <= ceiling)


def difficulty_rating(regions):
    """Provisional five ranks for normal 9x9 rule scores."""
    score = score_regions(regions, deadline=time.monotonic() + 3)
    if score is None:
        return None
    return {'rank': rank_for(score), 'score': score}


def rated_points(regions):
    """Clear points from the complete rule score, without a time budget, so
    the award never depends on server load."""
    score = score_regions(regions)
    return UNRATED_POINTS if score is None else RANK_POINTS[rank_for(score)]
