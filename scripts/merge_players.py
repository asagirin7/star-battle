"""Owner-run maintenance; dry-run by default. Never exposes login credentials."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from config import database_url
from player_maintenance import consolidate, preview


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--account',required=True)
    parser.add_argument('--source-id',required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--expected-target-id')
    parser.add_argument('--expected-source-name')
    args=parser.parse_args()
    engine=create_engine(database_url(),pool_size=1,max_overflow=0)
    with Session(engine) as session:
        report=preview(session,args.account,args.source_id)
        print('PLAYER_MERGE_PREVIEW '+json.dumps(report,ensure_ascii=False),flush=True)
        if args.apply:
            if not args.expected_source_name:
                parser.error('--apply requires --expected-source-name')
            target_id=args.expected_target_id or report['target']['id']
            with session.begin_nested():
                if target_id==args.source_id:
                    result={'already_merged':True,'target':report['target']}
                else:
                    result=consolidate(session,args.account,args.source_id,target_id,args.expected_source_name)
            session.commit()
            print('PLAYER_MERGE_APPLIED '+json.dumps(result,ensure_ascii=False),flush=True)
    engine.dispose()


if __name__=='__main__':
    main()
