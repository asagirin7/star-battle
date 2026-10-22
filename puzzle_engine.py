"""Generate connected, uniquely solvable puzzles on demand; never send solutions."""
import hashlib
import json
import random
import time

LEVELS = {'easy': (6, 3), 'medium': (7, 3), 'hard': (8, 3)}
INITIAL_LIVES = 3


def solutions(regions, limit=2):
    n = len(regions)
    found = []
    def visit(cols, used):
        r = len(cols)
        if r == n:
            found.append(cols[:])
            return
        for c in range(n):
            region = regions[r][c]
            if c in cols or region in used or (cols and abs(cols[-1]-c) <= 1):
                continue
            visit(cols + [c], used | {region})
            if len(found) >= limit:
                return
    visit([], set())
    return found


def fingerprint(regions):
    # Ignore arbitrary region labels when checking whether a board already exists.
    labels = {}
    normalized = []
    for row in regions:
        normalized.append([labels.setdefault(x, len(labels)) for x in row])
    return hashlib.sha256(json.dumps(normalized).encode()).hexdigest()


def generate(difficulty, rng=None, timeout=5):
    rng = rng or random.SystemRandom()
    n, points = LEVELS[difficulty]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        cols = list(range(n))
        rng.shuffle(cols)
        if any(abs(cols[r] - cols[r-1]) <= 1 for r in range(1, n)):
            continue
        regions = [[-1] * n for _ in range(n)]
        for r, c in enumerate(cols):
            regions[r][c] = r
        frontier = list(enumerate(cols))
        while frontier:
            r, c = rng.choice(frontier)
            neighbors = [(rr, cc) for rr, cc in [(r-1,c), (r+1,c), (r,c-1), (r,c+1)]
                         if 0 <= rr < n and 0 <= cc < n and regions[rr][cc] == -1]
            if not neighbors:
                frontier.remove((r, c))
                continue
            rr, cc = rng.choice(neighbors)
            regions[rr][cc] = regions[r][c]
            frontier.append((rr, cc))
        if len(solutions(regions)) == 1:
            return dict(size=n, difficulty=difficulty, points=points, regions=regions,
                        solution=cols, fingerprint=fingerprint(regions))
    raise TimeoutError('Unique puzzle generation exceeded time budget')
