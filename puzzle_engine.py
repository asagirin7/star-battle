"""Generate connected, uniquely solvable puzzles on demand; never send solutions."""
import hashlib
import json
import random
import time
import threading

EXPERT_POINTS = 100
LEVELS = {'easy': (6, 3), 'medium': (7, 6), 'hard': (8, 9), 'expert': (9, EXPERT_POINTS), 'expert_relaxed': (9, EXPERT_POINTS)}
INITIAL_LIVES = 3


def multiplier(size):
    return None if size == 9 else size - 5



def life_limit(size):
    return 1 if size == 9 else INITIAL_LIVES


def clear_points(size, mistakes):
    if mistakes >= life_limit(size):
        return 0
    return EXPERT_POINTS if size == 9 else (INITIAL_LIVES-mistakes)*multiplier(size)


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


def valid_area(regions, area, relaxed=False):
    n = len(regions)
    cells = {(r,c) for r in range(n) for c in range(n) if regions[r][c] == area}
    if len(cells) < (2 if relaxed else 3) or (not relaxed and (len({r for r,c in cells}) < 2 or len({c for r,c in cells}) < 2)):
        return False
    seen = {next(iter(cells))}
    todo = list(seen)
    while todo:
        r,c = todo.pop()
        for rr,cc in [(r-1,c),(r+1,c),(r,c-1),(r,c+1)]:
            if (rr,cc) in cells and (rr,cc) not in seen:
                seen.add((rr,cc));todo.append((rr,cc))
    return seen == cells


def easier_clues(regions):
    counts = [sum(row.count(i) for row in regions) for i in range(len(regions))]
    return counts.count(2) >= 2


def challenging_regions(regions, cols, rng, deadline, relaxed=False):
    """Refine connected areas while preserving the planted solution."""
    n = len(regions)
    fixed = {(r,c) for r,c in enumerate(cols)}
    if not all(valid_area(regions,i,relaxed) for i in range(n)):
        return False
    if relaxed and not easier_clues(regions):
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
            if valid_area(regions,old,relaxed) and valid_area(regions,target,relaxed) and (not relaxed or easier_clues(regions)):
                possible = solutions(regions, limit=100)
                if len(possible) <= len(current):
                    current = possible;changed = True
                    break
            regions[r][c] = old
        if not changed:
            return False
    return False


def _generate(difficulty, rng=None, timeout=5):
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
            if difficulty in {'expert','expert_relaxed'}:
                smallest = min(sizes[regions[r][c]] for r,c in frontier)
                choices = [(r,c) for r,c in frontier if sizes[regions[r][c]] == smallest] if smallest < (2 if difficulty == 'expert_relaxed' else 4) else frontier
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
        if difficulty in {'expert','expert_relaxed'} and not challenging_regions(regions, cols, rng, deadline, difficulty == 'expert_relaxed'):
            continue
        if len(solutions(regions)) == 1:
            return dict(size=n, difficulty=difficulty, points=points, regions=regions,
                        solution=cols, fingerprint=fingerprint(regions))
    raise TimeoutError('Unique puzzle generation exceeded time budget')


_expert_lock = threading.Lock()
_expert_seeds = {}


def vary_expert(seed, rng):
    """Walk between unique boards, retaining connectivity and area constraints."""
    n = seed['size']
    difficulty = seed.get('difficulty','expert')
    relaxed = difficulty == 'expert_relaxed'
    regions = [row[:] for row in seed['regions']]
    stars = set(enumerate(seed['solution']))
    for _ in range(rng.randrange(4)):
        regions = [list(row) for row in zip(*regions[::-1])]
        stars = {(c,n-1-r) for r,c in stars}
    if rng.randrange(2):
        regions = [row[::-1] for row in regions]
        stars = {(r,n-1-c) for r,c in stars}
    cols = [c for r,c in sorted(stars)]
    candidates = [(r,c) for r in range(n) for c in range(n) if (r,c) not in stars]
    rng.shuffle(candidates)
    changed = 0
    target_changes = rng.randint(3,8)
    for r,c in candidates:
        targets = list({regions[rr][cc] for rr,cc in [(r-1,c),(r+1,c),(r,c-1),(r,c+1)]
                        if 0 <= rr < n and 0 <= cc < n} - {regions[r][c]})
        rng.shuffle(targets)
        for target in targets:
            old = regions[r][c]
            regions[r][c] = target
            if valid_area(regions,old,relaxed) and valid_area(regions,target,relaxed) and (not relaxed or easier_clues(regions)) and len(solutions(regions)) == 1:
                changed += 1
                break
            regions[r][c] = old
        if changed >= target_changes:
            break
    if not changed:
        return None
    return dict(size=n, difficulty=difficulty, points=EXPERT_POINTS, regions=regions,
                solution=cols, fingerprint=fingerprint(regions))



def seed_expert(puzzle):
    """Restore a private starting layout after a process restart."""
    difficulty = puzzle['difficulty']
    relaxed = difficulty == 'expert_relaxed'
    with _expert_lock:
        if difficulty not in _expert_seeds and puzzle['size'] == 9:
            regions = puzzle['regions']
            if (all(valid_area(regions,i,relaxed) for i in range(9))
                    and (not relaxed or easier_clues(regions))
                    and solutions(regions) == [puzzle['solution']]):
                _expert_seeds[difficulty] = puzzle


def generate(difficulty, rng=None, timeout=5):
    # Keep seeded generation reproducible. Live challenges reuse only a private
    # starting layout, changing the areas and rechecking uniqueness every time.
    if difficulty not in {'expert','expert_relaxed'} or rng is not None:
        return _generate(difficulty,rng,timeout)
    with _expert_lock:
        seed = _expert_seeds.get(difficulty)
        varied = vary_expert(seed,random.SystemRandom()) if seed else None
        result = varied or _generate(difficulty,timeout=timeout)
        _expert_seeds[difficulty] = result
        return result
