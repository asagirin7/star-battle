"""Build reproducible connected-region puzzles, retaining only unique solutions."""
import json
import random
from pathlib import Path


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
            visit(cols+[c], used | {region})
            if len(found) >= limit:
                return
    visit([], set())
    return found


def generate():
    rng = random.Random(20261022)
    puzzles = []
    for n, difficulty, points in [(6, 'easy', 100), (7, 'medium', 180), (8, 'hard', 280)]:
        count = 0
        while count < 12:
            cols = list(range(n))
            rng.shuffle(cols)
            if any(abs(cols[r]-cols[r-1]) <= 1 for r in range(1,n)):
                continue
            regions = [[-1]*n for _ in range(n)]
            for r,c in enumerate(cols):
                regions[r][c] = r
            frontier = [(r,c) for r,c in enumerate(cols)]
            while frontier:
                r,c = rng.choice(frontier)
                neighbors = [(rr,cc) for rr,cc in [(r-1,c),(r+1,c),(r,c-1),(r,c+1)]
                             if 0 <= rr < n and 0 <= cc < n and regions[rr][cc] == -1]
                if not neighbors:
                    frontier.remove((r,c))
                    continue
                rr,cc = rng.choice(neighbors)
                regions[rr][cc] = regions[r][c]
                frontier.append((rr,cc))
            if len(solutions(regions)) != 1:
                continue
            count += 1
            puzzles.append(dict(id=f'{difficulty}-{count:02}', size=n, difficulty=difficulty,
                                points=points, regions=regions))
    Path(__file__).resolve().parents[1].joinpath('puzzles.json').write_text(json.dumps(puzzles, separators=(',', ':'))+'\n')


if __name__ == '__main__':
    generate()
