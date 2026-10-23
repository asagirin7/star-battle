"""Deterministic deductions only: no trial placements or access to a saved answer."""
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class LogicResult:
    solved: bool
    columns: tuple
    rounds: int
    remaining: int


def logical_result(regions):
    return _logical_result(tuple(tuple(row) for row in regions))


@lru_cache(maxsize=2048)
def _logical_result(regions):
    n=len(regions)
    full=(1 << (n*n))-1
    rows=[sum(1 << (r*n+c) for c in range(n)) for r in range(n)]
    cols=[sum(1 << (r*n+c) for r in range(n)) for c in range(n)]
    areas=[sum(1 << (r*n+c) for r in range(n) for c in range(n) if regions[r][c]==i) for i in range(n)]
    groups=[rows,cols,areas]
    units=rows+cols+areas
    conflicts=[]
    for r in range(n):
        for c in range(n):
            adjacent=sum(1 << (rr*n+cc) for rr in range(max(0,r-1),min(n,r+2))
                         for cc in range(max(0,c-1),min(n,c+2)))
            conflicts.append(rows[r] | cols[c] | areas[regions[r][c]] | adjacent)
    active=full
    rounds=0
    while True:
        rounds+=1
        before=active
        # A unit needs one star. Cells forbidden by every remaining candidate
        # of that unit can be excluded, without choosing any candidate.
        for unit in units:
            candidates=unit & active
            if not candidates:
                return LogicResult(False,(),rounds,active.bit_count())
            common=full
            todo=candidates
            while todo:
                bit=todo & -todo;todo^=bit
                common &= conflicts[bit.bit_length()-1]
            active &= ~(common & ~candidates)
        if all((unit & active).bit_count()==1 for unit in units):
            columns=tuple((row & active).bit_length()-1-r*n for r,row in enumerate(rows))
            if all(abs(columns[r]-columns[r-1])>1 for r in range(1,n)):
                return LogicResult(True,columns,rounds,active.bit_count())
        if active!=before:
            continue
        # Hall sets between row/column/region partitions: k required units
        # confined to k units of another kind reserve those destinations.
        remove=0
        for source in groups:
            domains=[unit & active for unit in source if (unit & active).bit_count()>1]
            m=len(domains)
            if m<2:
                continue
            unions=[0]*(1 << m)
            for subset in range(1,1 << m):
                bit=subset & -subset
                unions[subset]=unions[subset^bit] | domains[bit.bit_length()-1]
            for target in groups:
                if target is source:
                    continue
                links=[sum(1 << i for i,unit in enumerate(target) if unit & domain) for domain in domains]
                destinations=[0]*(1 << m)
                for subset in range(1,1 << m):
                    bit=subset & -subset
                    destination=destinations[subset^bit] | links[bit.bit_length()-1]
                    destinations[subset]=destination
                    count=subset.bit_count()
                    if count<2:
                        continue
                    if destination.bit_count()<count:
                        return LogicResult(False,(),rounds,active.bit_count())
                    if destination.bit_count()==count:
                        covered=0
                        todo=destination
                        while todo:
                            chosen=todo & -todo;todo^=chosen
                            covered |= target[chosen.bit_length()-1]
                        remove |= covered & active & ~unions[subset]
        active &= ~remove
        if active==before:
            return LogicResult(False,(),rounds,active.bit_count())
