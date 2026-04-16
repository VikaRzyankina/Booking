from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from app.db import get_db_cursor

user_bp = Blueprint('user', __name__, url_prefix='/')


@user_bp.route('/')
def index():
    return redirect(url_for('user.login'))


@user_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        login = request.form.get('login', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()

        if not all([login, password, full_name, phone]):
            flash('Все поля обязательны для заполнения')
            return render_template('user/register.html')

        password_hash = generate_password_hash(password)

        try:
            with get_db_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO users (login, password_hash, full_name, phone)
                    VALUES (%s, %s, %s, %s)
                """, (login, password_hash, full_name, phone))
            flash('Регистрация успешна! Теперь вы можете войти.')
            return redirect(url_for('user.login'))
        except Exception:
            flash('Пользователь с таким логином или телефоном уже зарегистрирован')
            return render_template('user/register.html')

    return render_template('user/register.html')


@user_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login = request.form.get('login', '').strip()
        password = request.form.get('password', '')

        if not login or not password:
            flash('Логин и пароль обязательны')
            return render_template('user/login.html')

        with get_db_cursor() as cur:
            cur.execute("SELECT id, password_hash FROM users WHERE login = %s", (login,))
            user = cur.fetchone()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            flash('Вы успешно вошли в систему')
            return redirect(url_for('user.user_page'))
        else:
            flash('Неверный логин или пароль')
            return render_template('user/login.html')

    return render_template('user/login.html')


@user_bp.route('/user')
def user_page():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему')
        return redirect(url_for('user.login'))

    with get_db_cursor() as cur:
        cur.execute("SELECT full_name, phone FROM users WHERE id = %s", (session['user_id'],))
        user_data = cur.fetchone()

    if not user_data:
        session.pop('user_id', None)
        flash('Сессия устарела, войдите снова')
        return redirect(url_for('user.login'))

    return render_template('user/profile.html',
                          full_name=user_data['full_name'], 
                          phone=user_data['phone'])


@user_bp.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему')
        return redirect(url_for('user.login'))

    with get_db_cursor() as cur:
        cur.execute("SELECT full_name, phone, password_hash FROM users WHERE id = %s", (session['user_id'],))
        user = cur.fetchone()

    if not user:
        session.pop('user_id', None)
        flash('Сессия устарела, войдите снова')
        return redirect(url_for('user.login'))

    if request.method == 'POST':
        cur_pass = request.form.get('current_password', '')
        new_pass = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()

        # Проверка текущего пароля
        if not check_password_hash(user['password_hash'], cur_pass):
            flash('Неверный текущий пароль')
            return render_template('user/settings.html', full_name=user['full_name'], phone=user['phone'])

        # Смена пароля только если новое поле заполнено
        password_hash = user['password_hash']
        if new_pass:
            if new_pass == confirm:
                password_hash = generate_password_hash(new_pass)
            else:
                flash('Новый пароль и подтверждение не совпадают')
                return render_template('user/settings.html', full_name=user['full_name'], phone=user['phone'])

        # Обновление данных
        try:
            with get_db_cursor(commit=True) as cur:
                cur.execute("""
                    UPDATE users
                    SET full_name = %s, phone = %s, password_hash = %s
                    WHERE id = %s
                """, (full_name, phone, password_hash, session['user_id']))
            flash('Настройки успешно обновлены')
            return redirect(url_for('user.user_page'))
        except Exception:
            flash('Пользователь с таким телефоном уже существует')
            return render_template('user/settings.html', full_name=full_name, phone=phone)

    return render_template('user/settings.html', full_name=user['full_name'], phone=user['phone'])


@user_bp.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Вы вышли из системы')
    return redirect(url_for('user.login'))
