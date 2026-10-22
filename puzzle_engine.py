"""Generate connected, uniquely solvable puzzles on demand; never send solutions."""
import hashlib
import json
import random
import time

LEVELS = {'easy': (6, 3), 'medium': (7, 6), 'hard': (8, 9), 'expert': (9, 30)}
INITIAL_LIVES = 3


def multiplier(size):
    return None if size == 9 else size - 5



def life_limit(size):
    return 1 if size == 9 else INITIAL_LIVES


def clear_points(size, mistakes):
    if mistakes >= life_limit(size):
        return 0
    return 30 if size == 9 else (INITIAL_LIVES-mistakes)*multiplier(size)


def solutions(regions, limit=2):
    n = len(regions)
    found, cols = [], []
    full = (1 << n)-1
    area_bits = [[1 << area for area in row] for row in regions]
    def visit(row, used_cols, used_areas, previous):
        if row == n:
            found.append(cols[:])
            return
        available = full & ~used_cols
        if previous >= 0:
            available &= ~((1 << previous) | (1 << (previous+1)) | ((1 << previous) >> 1))
        while available:
            bit = available & -available
            available ^= bit
            col = bit.bit_length()-1
            area = area_bits[row][col]
            if used_areas & area:
                continue
            cols.append(col)
            visit(row+1, used_cols | bit, used_areas | area, col)
            cols.pop()
            if len(found) >= limit:
                return
    visit(0, 0, 0, -1)
    return found


def fingerprint(regions):
    # Ignore arbitrary region labels when checking whether a board already exists.
    labels = {}
    normalized = []
    for row in regions:
        normalized.append([labels.setdefault(x, len(labels)) for x in row])
    return hashlib.sha256(json.dumps(normalized).encode()).hexdigest()


def challenging_regions(regions, cols, rng, deadline):
    """Refine connected areas while preserving the planted solution."""
    n = len(regions)
    fixed = {(r,c) for r,c in enumerate(cols)}
    def valid(area):
        cells = {(r,c) for r in range(n) for c in range(n) if regions[r][c] == area}
        if len(cells) < 3 or len({r for r,c in cells}) < 2 or len({c for r,c in cells}) < 2:
            return False
        seen = {next(iter(cells))}
        todo = list(seen)
        while todo:
            r,c = todo.pop()
            for rr,cc in [(r-1,c),(r+1,c),(r,c-1),(r,c+1)]:
                if (rr,cc) in cells and (rr,cc) not in seen:
                    seen.add((rr,cc));todo.append((rr,cc))
        return seen == cells
    if not all(valid(i) for i in range(n)):
        return False
    current = solutions(regions, limit=100)
    for _ in range(250):
        if len(current) == 1:
            return True
        if time.monotonic() >= deadline:
            return False
        alternate = rng.choice([s for s in current if s != cols])
        candidates = []
        for r,c in enumerate(alternate):
            if (r,c) in fixed:
                continue
            for rr,cc in [(r-1,c),(r+1,c),(r,c-1),(r,c+1)]:
                if 0 <= rr < n and 0 <= cc < n and regions[rr][cc] != regions[r][c]:
                    candidates.append((r,c,regions[rr][cc]))
        rng.shuffle(candidates)
        changed = False
        for r,c,target in candidates:
            old = regions[r][c]
            regions[r][c] = target
            if valid(old) and valid(target):
                possible = solutions(regions, limit=100)
                if len(possible) <= len(current):
                    current = possible;changed = True
                    break
            regions[r][c] = old
        if not changed:
            return False
    return False


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
        sizes = [1]*n
        while frontier:
            if difficulty == 'expert':
                smallest = min(sizes[regions[r][c]] for r,c in frontier)
                choices = [(r,c) for r,c in frontier if sizes[regions[r][c]] == smallest] if smallest < 4 else frontier
                r,c = rng.choice(choices)
            else:
                r, c = rng.choice(frontier)
            neighbors = [(rr, cc) for rr, cc in [(r-1,c), (r+1,c), (r,c-1), (r,c+1)]
                         if 0 <= rr < n and 0 <= cc < n and regions[rr][cc] == -1]
            if not neighbors:
                frontier.remove((r, c))
                continue
            rr, cc = rng.choice(neighbors)
            regions[rr][cc] = regions[r][c]
            sizes[regions[r][c]] += 1
            frontier.append((rr, cc))
        if difficulty == 'expert' and not challenging_regions(regions, cols, rng, deadline):
            continue
        if len(solutions(regions)) == 1:
            return dict(size=n, difficulty=difficulty, points=points, regions=regions,
                        solution=cols, fingerprint=fingerprint(regions))
    raise TimeoutError('Unique puzzle generation exceeded time budget')
