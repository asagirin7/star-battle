"""Password derivation and opaque, revocable device sessions."""
import hashlib
import hmac
import os
import secrets
import time

from fastapi import HTTPException
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

from models import AuthLimit, LoginSession

SESSION_DAYS = 30


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                            n=32768, r=8, p=3, maxmem=64*1024*1024).hex()
    return f'scrypt$32768$8$3${salt}${digest}'


def password_matches(password, encoded):
    return hmac.compare_digest(password_hash(password, encoded.split('$')[4]), encoded)


DUMMY_HASH = password_hash('not-a-real-account-password')


def issue_session(session, response, player_id):
    token = secrets.token_urlsafe(32)
    session.execute(delete(LoginSession).where(LoginSession.expires_at < time.time()))
    session.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                             player_id=player_id, expires_at=time.time()+SESSION_DAYS*86400))
    set_cookie(response, token)


def set_cookie(response, token):
    response.set_cookie('star_player', token, max_age=SESSION_DAYS*86400, httponly=True,
                        secure=os.getenv('COOKIE_SECURE', 'false').lower() == 'true',
                        samesite='strict', path='/')


def throttle(session, scope, value, limit, seconds=900):
    key = hashlib.sha256(f'{scope}:{value}'.encode()).hexdigest()
    now = time.time()
    session.execute(delete(AuthLimit).where(AuthLimit.window_start < now-86400))
    existing = session.get(AuthLimit, key)
    if not existing:
        try:
            session.add(AuthLimit(key=key, attempts=0, window_start=now))
            session.commit()
        except IntegrityError:
            session.rollback()
    session.execute(update(AuthLimit).where(AuthLimit.key==key, AuthLimit.window_start < now-seconds)
                    .values(attempts=0, window_start=now))
    count = session.execute(update(AuthLimit).where(AuthLimit.key==key)
                            .values(attempts=AuthLimit.attempts+1).returning(AuthLimit.attempts)).scalar_one()
    session.commit()
    if count > limit:
        raise HTTPException(429, '試行回数が多いため、15分ほど待ってからお試しください。')
