import os
from zoneinfo import ZoneInfo

DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_PORT = int(os.environ.get('DB_PORT', 5432))
DB_NAME = os.environ.get('DB_NAME', 'booking')
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '1234561')

SECRET_KEY = os.environ.get('SECRET_KEY', 'ОднаждыТутБудетКлюч')

TZ = ZoneInfo(os.environ.get('TZ_NAME', 'Europe/Moscow'))
RATING_MIN_VOTES = int(os.environ.get('RATING_MIN_VOTES', 5))

ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@example.com')

PAYMENT_ENABLED = os.environ.get('PAYMENT_ENABLED', 'true').lower() == 'true'
PAYMENT_REFUND_TIMEOUT_HOURS = int(os.environ.get('PAYMENT_REFUND_TIMEOUT_HOURS', 24))

FLASK_DEBUG = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
