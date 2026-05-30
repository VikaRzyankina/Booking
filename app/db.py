import psycopg2
import psycopg2.extras
from contextlib import contextmanager

import config

DB_CONFIG = {
    'host': config.DB_HOST,
    'port': config.DB_PORT,
    'dbname': config.DB_NAME,
    'user': config.DB_USER,
    'password': config.DB_PASSWORD,
}

DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
RATING_MIN_VOTES = config.RATING_MIN_VOTES


def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)


@contextmanager
def get_db_cursor(commit=False):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()