import os
from sqlalchemy import URL


def database_url():
    url = os.getenv('DATABASE_URL')
    if url:
        for prefix in ('postgres://', 'postgresql://'):
            if url.startswith(prefix):
                return url.replace(prefix, 'postgresql+psycopg://', 1)
        return url
    if os.getenv('DB_HOST'):
        return URL.create('postgresql+psycopg', username=os.getenv('DB_USER'),
                          password=os.getenv('DB_PASSWORD'), host=os.getenv('DB_HOST'),
                          port=int(os.getenv('DB_PORT', '5432')), database=os.getenv('DB_NAME'))
    return 'sqlite:///star-battle.db'
