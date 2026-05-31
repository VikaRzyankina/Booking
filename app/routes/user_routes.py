import re

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from app.db import get_db_cursor

_LOGIN_RE = re.compile(r'^[a-zA-Z_0-9.\-]+$')
_PHONE_RE = re.compile(r'^(\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}$')


def _valid_login(login: str) -> bool:
    return bool(_LOGIN_RE.match(login))


def _valid_phone(phone: str) -> bool:
    return bool(_PHONE_RE.match(phone))

user_bp = Blueprint('user', __name__, url_prefix='/')


def _back_url():
    ref = request.referrer
    if ref and ref.startswith('/'):
        return ref
    from urllib.parse import urlparse
    if ref and urlparse(ref).netloc == urlparse(request.host_url).netloc:
        return ref
    return url_for('building.browse')


def _load_current_user():
    user_id = session.get('user_id')
    if not user_id:
        flash('Пожалуйста, войдите в систему')
        return None, redirect(_back_url())
    with get_db_cursor() as cur:
        cur.execute("SELECT full_name, phone, password_hash FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
    if not user:
        session.pop('user_id', None)
        flash('Сессия устарела, войдите снова')
        return None, redirect(_back_url())
    return user, None


@user_bp.route('/')
def index():
    return redirect(url_for('building.browse'))


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

        if not _valid_login(login):
            flash('Логин может содержать только латинские буквы, цифры и символы _ . -')
            return render_template('user/register.html')

        if not _valid_phone(phone):
            flash('Телефон должен быть в формате +7 (999) 000-00-00 или 8 999 000-00-00')
            return render_template('user/register.html')

        password_hash = generate_password_hash(password)

        try:
            with get_db_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO users (login, password_hash, full_name, phone)
                    VALUES (%s, %s, %s, %s)
                """, (login, password_hash, full_name, phone))
            flash('Регистрация успешна! Теперь вы можете войти.')
            return redirect(url_for('building.browse'))
        except Exception:
            flash('Пользователь с таким логином или телефоном уже зарегистрирован')
            return render_template('user/register.html')

    return render_template('user/register.html')


@user_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_val = request.form.get('login', '').strip()
        password = request.form.get('password', '')
        next_url = request.form.get('next', '')
        if not next_url.startswith('/'):
            next_url = url_for('building.browse')

        if not login_val or not password:
            flash('Логин и пароль обязательны')
            return redirect(next_url)

        with get_db_cursor() as cur:
            cur.execute("SELECT id, password_hash FROM users WHERE login = %s", (login_val,))
            user = cur.fetchone()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            flash('Вы успешно вошли в систему!')
            return redirect(next_url)
        else:
            flash('Неверный логин или пароль.', 'error')
            return redirect(next_url)

    return redirect(url_for('building.browse'))


@user_bp.route('/user')
def user_page():
    return redirect(url_for('building.browse'))


@user_bp.route('/settings', methods=['GET', 'POST'])
def settings():
    user, err = _load_current_user()
    if err:
        return err

    if request.method == 'POST':
        new_pass = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()

        if phone and not _valid_phone(phone):
            flash('Телефон должен быть в формате +7 (999) 000-00-00 или 8 999 000-00-00')
            return render_template('user/settings.html', full_name=user['full_name'], phone=user['phone'])

        password_hash = user['password_hash']
        if new_pass:
            cur_pass = request.form.get('current_password', '')
            if not check_password_hash(user['password_hash'], cur_pass):
                flash('Неверный текущий пароль')
                return render_template('user/settings.html', full_name=user['full_name'], phone=user['phone'])

            if new_pass != confirm:
                flash('Новый пароль и подтверждение не совпадают')
                return render_template('user/settings.html', full_name=user['full_name'], phone=user['phone'])

            password_hash = generate_password_hash(new_pass)

        try:
            with get_db_cursor(commit=True) as cur:
                cur.execute("""
                    UPDATE users
                    SET full_name = %s, phone = %s, password_hash = %s
                    WHERE id = %s
                """, (full_name, phone, password_hash, session['user_id']))
            flash('Настройки успешно обновлены')
            return redirect(url_for('building.browse'))
        except Exception:
            flash('Пользователь с таким телефоном уже существует')
            return render_template('user/settings.html', full_name=full_name, phone=phone)

    return render_template('user/settings.html', full_name=user['full_name'], phone=user['phone'])


@user_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    session.pop('user_id', None)
    flash('Вы вышли из системы')
    next_url = request.form.get('next', '')
    if not next_url.startswith('/'):
        next_url = url_for('building.browse')
    return redirect(next_url)
