import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'dbname': 'booking',
    'user': 'postgres',
    'password': '1234561'
}


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