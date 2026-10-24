"""Generate connected, uniquely solvable puzzles on demand; never send solutions."""
import hashlib
import json
import random
import time
import threading
from functools import lru_cache
from collections import deque
from logic_solver import logical_result
from adaptive_difficulty import allows_score, score_regions, choose_candidate, target_score

# Close enough to the streak target to stop walking (about half a rank).
WALK_TOLERANCE = 8

EXPERT_POINTS = 100
RELAXED_POINTS = 50
LEVELS = {'easy': (6, 3), 'medium': (7, 6), 'hard': (8, 9), 'expert': (9, EXPERT_POINTS), 'expert_relaxed': (9, RELAXED_POINTS)}
INITIAL_LIVES = 3


def multiplier(size):
    return None if size == 9 else size - 5



def life_limit(size):
    return 1 if size == 9 else INITIAL_LIVES


def clear_points(size, mistakes, difficulty=None):
    if mistakes >= life_limit(size):
        return 0
    if size == 9:
        return RELAXED_POINTS if difficulty == 'expert_relaxed' else EXPERT_POINTS
    return (INITIAL_LIVES-mistakes)*multiplier(size)


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



class InvalidPuzzle(ValueError):
    pass


def valid_stars(regions, stars, complete=False):
    """Check the game rules directly, independently of the search algorithm."""
    n = len(regions)
    stars = list(stars)
    if complete and len(stars) != n:
        return False
    rows, columns, areas = set(), set(), set()
    for r,c in stars:
        if type(r) is not int or type(c) is not int or not (0 <= r < n and 0 <= c < n):
            return False
        area = regions[r][c]
        if r in rows or c in columns or area in areas:
            return False
        rows.add(r);columns.add(c);areas.add(area)
    return all(max(abs(r-rr),abs(c-cc)) > 1
               for i,(r,c) in enumerate(stars) for rr,cc in stars[i+1:])


@lru_cache(maxsize=1024)
def _checked_solution(regions):
    n = len(regions)
    for area in range(n):
        cells = {(r,c) for r in range(n) for c in range(n) if regions[r][c] == area}
        visited = {next(iter(cells))}
        todo = list(visited)
        while todo:
            r,c = todo.pop()
            for neighbor in [(r-1,c),(r+1,c),(r,c-1),(r,c+1)]:
                if neighbor in cells and neighbor not in visited:
                    visited.add(neighbor);todo.append(neighbor)
        if visited != cells:
            raise InvalidPuzzle('Disconnected area')
    found = solutions(regions)
    if len(found) != 1 or not valid_stars(regions,enumerate(found[0]),complete=True):
        raise InvalidPuzzle('Puzzle must have exactly one rule-valid solution')
    return tuple(found[0])


def checked_solution(regions):
    n = len(regions)
    if not 6 <= n <= 9 or any(not isinstance(row,(list,tuple)) or len(row) != n for row in regions):
        raise InvalidPuzzle('Invalid board dimensions')
    if any(type(area) is not int or not 0 <= area < n for row in regions for area in row):
        raise InvalidPuzzle('Invalid area label')
    if {area for row in regions for area in row} != set(range(n)):
        raise InvalidPuzzle('Missing area')
    return list(_checked_solution(tuple(tuple(row) for row in regions)))


def certify_generated(puzzle):
    level = puzzle['difficulty']
    size,points = LEVELS[level]
    regions = puzzle['regions']
    canonical = checked_solution(regions)
    if len(regions) != size or puzzle['size'] != size or puzzle['solution'] != canonical:
        raise InvalidPuzzle('Stored solution does not match board')
    if puzzle['points'] != points or puzzle['fingerprint'] != fingerprint(regions):
        raise InvalidPuzzle('Invalid puzzle metadata')
    deduction = logical_result(regions)
    if not deduction.solved or list(deduction.columns) != canonical:
        raise InvalidPuzzle('Puzzle requires deductions beyond supported non-trial rules')
    if level.startswith('expert'):
        relaxed = level == 'expert_relaxed'
        if not all(valid_area(regions,i,relaxed) for i in range(size)) or (relaxed and not easier_clues(regions)):
            raise InvalidPuzzle('Invalid difficulty constraints')
    return puzzle


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


def _generate(difficulty, rng=None, timeout=5, style=None):
    rng = rng or random.SystemRandom()
    n, points = LEVELS[difficulty]
    deadline = time.monotonic() + timeout
    shape = style or rng.choice(['compact','compact','compact','vertical','horizontal','cross'])
    while time.monotonic() < deadline:
        cols = list(range(n))
        rng.shuffle(cols)
        if any(abs(cols[r] - cols[r-1]) <= 1 for r in range(1, n)):
            continue
        regions = [[-1] * n for _ in range(n)]
        for r, c in enumerate(cols):
            regions[r][c] = r
        if shape in {'vertical','horizontal','cross'}:
            roots = [r for r,c in enumerate(cols) if 1 <= r < n-1 and 1 <= c < n-1]
            root = rng.choice(roots or list(range(n)))
            if shape in {'horizontal','cross'}:
                for c in range(n):
                    regions[root][c] = root
            if shape in {'vertical','cross'}:
                for r in range(n):
                    regions[r][cols[root]] = root
        frontier = [(r,c) for r in range(n) for c in range(n) if regions[r][c] != -1]
        sizes = [sum(row.count(i) for row in regions) for i in range(n)]
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
        if shape == 'compact' and spanning_shapes(regions):
            continue
        if solutions(regions) == [cols] and logical_result(regions).solved:
            labels = list(range(n));rng.shuffle(labels)
            regions = [[labels[area] for area in row] for row in regions]
            return dict(size=n, difficulty=difficulty, points=points, regions=regions,
                        solution=cols, fingerprint=fingerprint(regions))
    raise TimeoutError('Unique puzzle generation exceeded time budget')


_expert_lock = threading.Lock()
_expert_seeds = {}
_recent_families = {}
_generation_counts = {}


def vary_expert(seed, rng, deadline=None):
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
        if deadline is not None and time.monotonic() >= deadline:
            break
        targets = list({regions[rr][cc] for rr,cc in [(r-1,c),(r+1,c),(r,c-1),(r,c+1)]
                        if 0 <= rr < n and 0 <= cc < n} - {regions[r][c]})
        rng.shuffle(targets)
        for target in targets:
            if deadline is not None and time.monotonic() >= deadline:
                break
            old = regions[r][c]
            regions[r][c] = target
            if valid_area(regions,old,relaxed) and valid_area(regions,target,relaxed) and (not relaxed or easier_clues(regions)) and len(solutions(regions)) == 1 and logical_result(regions).solved:
                changed += 1
                break
            regions[r][c] = old
        if changed >= target_changes:
            break
    if not changed:
        return None
    return certify_generated(dict(size=n, difficulty=difficulty, points=LEVELS[difficulty][1], regions=regions,
                solution=cols, fingerprint=fingerprint(regions)))



def solution_family(cols):
    """Canonicalize rotations/reflections so they do not count as fresh layouts."""
    n = len(cols)
    stars = set(enumerate(cols))
    variants = []
    for _ in range(4):
        variants.append(tuple(c for r,c in sorted(stars)))
        variants.append(tuple(n-1-c for r,c in sorted(stars)))
        stars = {(c,n-1-r) for r,c in stars}
    return min(variants)


def spanning_shapes(regions):
    n = len(regions)
    shapes = set()
    for area in range(n):
        rows = {r for r in range(n) for c in range(n) if regions[r][c] == area}
        cols = {c for r in range(n) for c in range(n) if regions[r][c] == area}
        if len(rows) == n:
            shapes.add('vertical')
        if len(cols) == n:
            shapes.add('horizontal')
        if len(rows) == n and len(cols) == n:
            shapes.add('cross')
    return shapes


def needs_seed(difficulty):
    with _expert_lock:
        return not _expert_seeds.get(difficulty)


def seed_expert(puzzle):
    """Restore multiple independently checked shapes after process restarts."""
    level = puzzle['difficulty']
    try:
        puzzle = dict(puzzle, points=LEVELS[level][1], fingerprint=fingerprint(puzzle['regions']))
        certify_generated(puzzle)
    except (InvalidPuzzle,KeyError,TypeError,ValueError):
        return
    with _expert_lock:
        bank = _expert_seeds.setdefault(level,deque(maxlen=32))
        if all(item['fingerprint'] != puzzle['fingerprint'] for item in bank):
            bank.append(puzzle)


def generate(difficulty, rng=None, timeout=5, streak=0):
    if rng is not None or not difficulty.startswith('expert'):
        return certify_generated(_generate(difficulty,rng,timeout))
    rng = random.SystemRandom()
    started = time.monotonic()
    with _expert_lock:
        bank = _expert_seeds.setdefault(difficulty,deque(maxlen=32))
        recent = _recent_families.setdefault(difficulty,deque(maxlen=6))
        count = _generation_counts.get(difficulty,0)
        _generation_counts[difficulty] = count+1
        styles = ['compact','vertical','compact','horizontal','cross','compact']
        desired = styles[count % len(styles)]
        result = None
        # Bound CPU work under load, while repeatedly injecting entirely new
        # planted solutions instead of only rotating one cached star placement.
        if not bank or count % 3 == 0:
            try:
                style = rng.choice(['vertical','horizontal','cross']) if not bank else styles[(count//3) % len(styles)]
                result = certify_generated(_generate(difficulty,timeout=timeout if not bank else min(timeout,.25),style=style))
            except TimeoutError:
                if not bank:
                    raise
        if result is None:
            shaped = [item for item in bank if (not spanning_shapes(item['regions']) if desired == 'compact' else desired in spanning_shapes(item['regions']))] or list(bank)
            choices = [item for item in shaped if solution_family(item['solution']) not in recent] or shaped
            for _ in range(5):
                result = vary_expert(rng.choice(choices),rng)
                if result:
                    break
        if result is None:
            result = certify_generated(_generate(difficulty,timeout=timeout))
        bank.append(result)
        if difficulty == 'expert':
            # Extra work shares the normal generation's original time budget.
            # Unselected candidates are discarded, so selection changes the
            # distribution, rather than merely reordering a mandatory queue.
            deadline = min(started + timeout, time.monotonic() + .8)
            fallback = result
            candidates = [result]
            initial_score = score_regions(result['regions'], deadline=deadline)
            eligible = [result] if initial_score is not None else []
            scores = [initial_score] if initial_score is not None else []
            seeds = [item for item in bank
                     if solution_family(item['solution']) not in recent
                     and solution_family(item['solution']) != solution_family(result['solution'])]
            rng.shuffle(seeds)
            # Several region variations per seed are fine: the streak target
            # needs a spread of scores, not distinct star layouts. A fresh
            # bank with no other family varies the generated board itself.
            sources = seeds or [result]
            for attempt in range(12):
                if len(candidates) >= 6 or time.monotonic() >= deadline:
                    break
                extra = vary_expert(sources[attempt % len(sources)], rng, deadline=deadline)
                if extra is not None and all(extra['fingerprint'] != item['fingerprint'] for item in candidates):
                    candidates.append(extra)
                    score = score_regions(extra['regions'], deadline=deadline)
                    if score is not None:
                        eligible.append(extra)
                        scores.append(score)
            # Variations stay close to their seed's score, so walk from the
            # candidate nearest the streak target towards that target.
            if scores:
                target = target_score(streak)
                walk_deadline = min(started + timeout, time.monotonic() + .6)
                nearest = min(range(len(scores)), key=lambda i: abs(scores[i]-target))
                base, distance = eligible[nearest], abs(scores[nearest]-target)
                while distance > WALK_TOLERANCE and time.monotonic() < walk_deadline:
                    extra = vary_expert(base, rng, deadline=walk_deadline)
                    if extra is None or any(extra['fingerprint'] == item['fingerprint'] for item in eligible):
                        continue
                    score = score_regions(extra['regions'], deadline=walk_deadline)
                    if score is None or not allows_score(score, streak):
                        continue
                    eligible.append(extra)
                    scores.append(score)
                    if abs(score-target) < distance:
                        base, distance = extra, abs(score-target)
            # Too hard for the current streak: spend a little more on one
            # allowed candidate rather than serving a master board early.
            if scores and not any(allows_score(s, streak) for s in scores):
                retry_deadline = time.monotonic() + 1
                for seed in seeds or list(bank):
                    if time.monotonic() >= retry_deadline:
                        break
                    extra = vary_expert(seed, rng, deadline=retry_deadline)
                    if extra is None:
                        continue
                    score = score_regions(extra['regions'], deadline=retry_deadline)
                    if score is not None and allows_score(score, streak):
                        eligible.append(extra)
                        scores.append(score)
                        break
            result = choose_candidate(eligible, scores, streak, rng) if eligible else fallback
        recent.append(solution_family(result['solution']))
        return certify_generated(result)
