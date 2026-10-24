"""Bounded, solution-free difficulty scoring and gentle candidate weighting."""
import random
import time
from collections import OrderedDict
from hint_engine import next_hint

# Immutable region layouts, not stored solutions, identify the scoring cache.
_scores = OrderedDict()
SCORE_CACHE_LIMIT = 128


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


def candidate_weights(scores, streak):
    """Tied scores have tied weights; at 20 wins high/low weight is only 1.8."""
    low, high = min(scores), max(scores)
    # Dense rank avoids uncalibrated score gaps dominating the distribution.
    levels = sorted(set(scores))
    strength = .04 * max(0, min(int(streak), 20))
    return [1 + strength * (levels.index(s)/(len(levels)-1) if low != high else 0)
            for s in scores]


def choose_candidate(candidates, scores, streak, rng=None):
    if not candidates or len(candidates) != len(scores):
        raise ValueError('Candidates and scores must be nonempty and aligned')
    return (rng or random.SystemRandom()).choices(
        candidates, weights=candidate_weights(scores, streak), k=1)[0]
