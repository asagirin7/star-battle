"""JST launch grants and idempotent hint spending; caller holds the player lock."""
import time
from models import HintWallet


def jst_day():
    return int((time.time()+9*3600)//86400)


def wallet_for_launch(session,player_id):
    today=jst_day()
    wallet=session.get(HintWallet,player_id,populate_existing=True)
    if wallet is None:
        wallet=HintWallet(player_id=player_id,balance=10,grant_day=today)
        session.add(wallet)
    elif today>wallet.grant_day:
        wallet.balance+=3
        wallet.grant_day=today
    session.flush()
    return wallet
