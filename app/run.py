import secrets

from flask import Flask
from werkzeug.security import generate_password_hash

from permissions import ALL_PERMISSIONS
from routes.building_routes import building_bp
from routes.room_routes import room_bp
from routes.user_routes import user_bp

app = Flask(__name__)
app.secret_key = 'ОднаждыТутБудетКлюч'

app.register_blueprint(user_bp)
app.register_blueprint(building_bp)
app.register_blueprint(room_bp)


def initialize_default_users():
    """
    Инициализирует стандартных пользователей admin (id=1) и guest (id=2)
    - Если пользователя с id=1 не существует, создаёт admin с паролем 'admin' и выдаёт ему все права
    - Если пользователя с id=2 не существует, создаёт guest со случайным длинным паролем и без каких-либо прав
    - Если у указанных пользователь не соответствующий логин, то бросает исключение
    """

    from db import get_db_cursor
    with get_db_cursor(commit=True) as cur:
        cur.execute("SELECT id, login FROM users WHERE id = 1")
        admin_row = cur.fetchone()

        if admin_row is None:
            password_hash = generate_password_hash('admin')
            cur.execute("""
                INSERT INTO users (id, login, password_hash, full_name, phone)
                VALUES (1, 'admin', %s, 'Administrator', 'admin@example.com')
            """, (password_hash,))
        else:
            if admin_row['login'] != 'admin':
                raise ValueError(f"User with id=1 exists but login is '{admin_row['login']}', expected 'admin'")
        for perm in ALL_PERMISSIONS:
            cur.execute("""
                INSERT INTO user_permissions (user_id, granter_id, permission, granting, building_id, room_id)
                VALUES (1, NULL, %s, TRUE, NULL, NULL)
                ON CONFLICT ON CONSTRAINT unique_user_permission_global DO NOTHING
            """, (perm,))

        cur.execute("SELECT id, login FROM users WHERE id = 2")
        guest_row = cur.fetchone()

        if guest_row is None:
            password_hash = generate_password_hash(''.join(
                secrets.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()")
                for _ in range(64)
            ))
            cur.execute("""
                INSERT INTO users (id, login, password_hash, full_name, phone)
                VALUES (2, 'guest', %s, 'Guest User', 'guest@example.com')
            """, (password_hash,))
        else:
            if guest_row['login'] != 'guest':
                raise ValueError(f"User with id=2 exists but login is '{guest_row['login']}', expected 'guest'")


if __name__ == '__main__':
    initialize_default_users()
    app.run(debug=True)

