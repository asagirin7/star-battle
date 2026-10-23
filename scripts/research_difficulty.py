"""Offline scan-order sensitivity probe. No human timing or production changes."""
import argparse
import json
import random
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from logic_solver import logical_result
from puzzle_engine import LEVELS, generate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay',type=Path,help='Recheck saved layouts without generating new boards')
    args=parser.parse_args()
    if args.replay:
        for sample in json.loads(args.replay.read_text()):
            actual=measure(sample['regions'],sample['solution'])
            assert actual==sample['rounds'], (sample['level'],sample['seed'])
        print('Saved layouts and all label permutations reproduced.')
        return
    rows=[]
    for level in LEVELS:
        for seed in range(5):
            board=generate(level,random.Random(seed+100))
            rounds=measure(board['regions'],board['solution'])
            rows.append(dict(level=level,seed=seed,generator_seed=seed+100,
                             regions=board['regions'],solution=board['solution'],
                             min_rounds=min(rounds),max_rounds=max(rounds),rounds=rounds))
    print(json.dumps(rows,indent=2))


def measure(regions,solution):
    rounds=[]
    for variant in range(20):
        labels=list(range(len(regions)))
        random.Random(variant).shuffle(labels)
        report=logical_result([[labels[a] for a in row] for row in regions])
        assert report.solved and list(report.columns)==solution
        rounds.append(report.rounds)
    return rounds


if __name__=='__main__':
    main()
