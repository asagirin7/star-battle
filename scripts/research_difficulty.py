"""Offline scan-order sensitivity probe. No human timing or production changes."""
import json
import random
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from logic_solver import logical_result
from puzzle_engine import LEVELS, generate


def main():
    rows=[]
    for level in LEVELS:
        for seed in range(5):
            board=generate(level,random.Random(seed+100))
            rounds=[]
            for variant in range(20):
                labels=list(range(board['size']))
                random.Random(variant).shuffle(labels)
                report=logical_result([[labels[a] for a in row] for row in board['regions']])
                assert report.solved and list(report.columns)==board['solution']
                rounds.append(report.rounds)
            rows.append(dict(level=level,seed=seed,min_rounds=min(rounds),max_rounds=max(rounds),rounds=rounds))
    print(json.dumps(rows,indent=2))


if __name__=='__main__':
    main()
