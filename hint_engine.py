"""Small, explainable one-step deductions; never searches or reads a solution."""
from itertools import combinations


def next_hint(regions, stars=(), crosses=()):
    """Return the cheapest applicable deduction, or None when these rules stall.

    Coordinates are zero based. Crosses are flat indexes. Invalid or locally
    contradictory input raises ValueError; global satisfiability is not searched.
    """
    n = len(regions)
    if not 1 <= n <= 12 or any(len(row) != n for row in regions):
        raise ValueError('正方形の盤面が必要です')
    try:
        labels = list(dict.fromkeys(v for row in regions for v in row))
        if len(labels) != n:
            raise ValueError('領域数が盤面サイズと一致しません')
        star_list = list(stars)
        if any(len(p) != 2 or any(type(v) is not int for v in p) or not all(0 <= v < n for v in p) for p in star_list):
            raise ValueError('星の座標が不正です')
        placed = {r*n+c for r, c in star_list}
        marked = set(crosses)
        if any(type(v) is not int or not 0 <= v < n*n for v in marked) or placed & marked:
            raise ValueError('メモの位置が不正です')
    except (TypeError, IndexError) as exc:
        raise ValueError('盤面の指定が不正です') from exc
    full = set(range(n*n))
    rows = [{r*n+c for c in range(n)} for r in range(n)]
    cols = [{r*n+c for r in range(n)} for c in range(n)]
    areas = [{r*n+c for r in range(n) for c in range(n) if regions[r][c] == label} for label in labels]
    groups = [rows, cols, areas]
    names = ['行', '列', '領域']
    units = rows+cols+areas
    conflicts = []
    for p in range(n*n):
        r, c = divmod(p, n)
        adjacent = {rr*n+cc for rr in range(max(0,r-1), min(n,r+2)) for cc in range(max(0,c-1), min(n,c+2))}
        conflicts.append(rows[r] | cols[c] | next(a for a in areas if p in a) | adjacent)
    if any((conflicts[p]-{p}) & placed for p in placed):
        raise ValueError('星が互いの条件に違反しています')
    forbidden = set().union(*(conflicts[p]-{p} for p in placed)) if placed else set()
    active = full - marked - forbidden
    if any(not u & active for u in units):
        raise ValueError('星を置けない行・列・領域があります。メモを確認してください')
    hints = []

    def add(technique, points, explanation, source, targets, action='cross'):
        targets = set(targets) - marked - placed
        if not targets:
            return
        hints.append(dict(technique=technique, points=points, explanation=explanation,
                          source_cells=[list(divmod(p,n)) for p in sorted(source)],
                          target_cells=[list(divmod(p,n)) for p in sorted(targets)], action=action))

    add('star_exclusion', 0, '置かれた星と同じ行・列・領域、および隣接するマスには星を置けません。', placed, forbidden)
    for unit in units:
        candidates = unit & active
        if unit & placed:
            continue
        if len(candidates) == 1:
            add('single_candidate', 1, 'この行・列・領域で星を置けるマスは、残り1マスです。', candidates, candidates, 'star')
    for source_kind, target_kind, cost, technique in [(2,0,2,'region_to_line'), (2,1,2,'region_to_line'), (0,2,4,'line_to_region'), (1,2,4,'line_to_region')]:
        for unit in groups[source_kind]:
            if unit & placed:
                continue
            candidates = unit & active
            for target in groups[target_kind]:
                if candidates <= target:
                    add(technique, cost, f'この{names[source_kind]}の星候補は1つの{names[target_kind]}に収まるため、その{names[target_kind]}の他の候補を除けます。', candidates, (target & active)-candidates)
    for row in rows:
        if row & placed:
            continue
        for col in cols:
            if col & placed:
                continue
            rc, cc = row & active, col & active
            for area in areas:
                if rc <= area and cc <= area:
                    add('same_region_intersection', 5, 'この行と列の星候補は同じ領域に収まります。その領域の星は1つなので、行と列の交点が星です。', rc|cc, row & col & active, 'star')
    # Hall sets in both partition directions; complementary sets receive the
    # same score and the stable minimum below returns only one deduction.
    for si, source in enumerate(groups):
        for ti, target in enumerate(groups):
            if si == ti:
                continue
            pending = [u for u in source if not u & placed]
            for k in range(2, len(pending)+1):
                m = min(k, n-k)
                if m < 2:
                    continue
                for subset in combinations(pending, k):
                    candidates = set().union(*(u & active for u in subset))
                    destinations = [u for u in target if u & candidates]
                    if len(destinations) < k:
                        raise ValueError('候補が不足しています。メモを確認してください')
                    if len(destinations) == k:
                        reserved = set().union(*destinations)
                        add('n_to_n', 3*m-1, f'{k}個の{names[si]}の候補が{k}個の{names[ti]}だけに収まります。その{names[ti]}はこれらの星に使うため、他の候補を除けます。', candidates, (reserved & active)-candidates)
    for unit in units:
        if unit & placed:
            continue
        candidates = unit & active
        if len(candidates) < 2:
            continue
        common = set.intersection(*(conflicts[p] for p in candidates))
        rs = {p//n for p in candidates}
        cs = {p%n for p in candidates}
        gaps = max(rs)-min(rs)+1-len(rs) + max(cs)-min(cs)+1-len(cs)
        add('shape_exclusion', 10+gaps, 'この行・列・領域のどの候補に星を置いても、対象マスは同じ行・列・領域または隣接の制約で置けなくなります。', candidates, (common & active)-candidates)
    if not hints:
        return None
    return min(hints, key=lambda h: (h['points'], h['technique'], h['target_cells'], h['source_cells']))
