#!/bin/sh
set -e

echo "==> Waiting for database..."
python -c "
import sys, time, psycopg2, os
host = os.getenv('DB_HOST', 'db')
port = int(os.getenv('DB_PORT', 5432))
dbname = os.getenv('DB_NAME', 'booking')
user = os.getenv('DB_USER', 'postgres')
password = os.getenv('DB_PASSWORD', '')
for i in range(30):
    try:
        conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password)
        conn.close()
        print('Database is ready.')
        sys.exit(0)
    except Exception as e:
        print(f'Attempt {i+1}/30: {e}')
        time.sleep(1)
print('Database not available after 30 attempts.')
sys.exit(1)
"

echo "==> Initializing database schema..."
python -m init_db

echo "==> Initializing default users..."
python -c "from run import initialize_default_users; initialize_default_users()"

echo "==> Starting Gunicorn..."
exec gunicorn --bind 0.0.0.0:5000 --workers 2 "run:app"
