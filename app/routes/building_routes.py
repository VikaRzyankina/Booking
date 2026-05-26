from datetime import date as date_type
from urllib.parse import urlencode

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort

from app.assets_manager import save_photo, validate_photo
from app.db import get_db_cursor, DAYS
from app.permissions import (require_permission, login_required, grant_permission, check_granting,
                             revoke_permission, PERMISSION_LABELS, VIEW, CREATE_BUILDING,
                             MANAGE_BUILDING, CREATE_ROOM, MANAGE_BOOKING_REQUESTS)

building_bp = Blueprint('building', __name__, url_prefix='/')

_BUILDING_PERM_LABELS = [(p, PERMISSION_LABELS[p]) for p in [VIEW, MANAGE_BUILDING, CREATE_ROOM, MANAGE_BOOKING_REQUESTS]]


def get_building(building_id):
    with get_db_cursor() as cur:
        cur.execute("SELECT id, city, street, description FROM buildings WHERE id = %s", (building_id,))
        return cur.fetchone()


def get_working_hours(building_id):
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT day_of_week, open_time, close_time, is_closed
            FROM working_hours
            WHERE building_id = %s
        """, (building_id,))
        rows = cur.fetchall()

    hours = {}
    for row in rows:
        hours[row['day_of_week']] = {
            'open_time': row['open_time'],
            'close_time': row['close_time'],
            'is_closed': row['is_closed']
        }
    return hours


def save_working_hours(cur, building_id, form_data):
    cur.execute("DELETE FROM working_hours WHERE building_id = %s", (building_id,))

    for day in DAYS:
        open_time = form_data.get(f'{day}_open_time')
        close_time = form_data.get(f'{day}_close_time')
        is_closed = form_data.get(f'{day}_is_closed') == 'on'

        if not is_closed:
            if not open_time or not close_time:
                raise ValueError(f"Для дня {day} необходимо указать время открытия и закрытия.")
        else:
            open_time = '00:00:00'
            close_time = '00:00:00'

        cur.execute("""
            INSERT INTO working_hours (building_id, day_of_week, open_time, close_time, is_closed)
            VALUES (%s, %s, %s, %s, %s)
        """, (building_id, day, open_time, close_time, is_closed))


def save_building_with_hours(cur, building_id, city, street, description, form_data):
    if building_id is None:
        cur.execute("""
            INSERT INTO buildings (city, street, description)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (city, street, description))
        building_id = cur.fetchone()[0]
    else:
        cur.execute("""
            UPDATE buildings
            SET city = %s, street = %s, description = %s
            WHERE id = %s
        """, (city, street, description, building_id))

    save_working_hours(cur, building_id, form_data)
    return building_id


@building_bp.route('/browse')
def browse():
    user_id = session.get('user_id', 2)

    filter_city = request.args.get('city', '').strip() or None
    filter_street = request.args.get('street', '').strip() or None
    filter_date_str = request.args.get('date', '').strip() or None
    filter_time_from = request.args.get('time_from', '').strip() or None
    filter_time_to = request.args.get('time_to', '').strip() or None

    day_of_week = None
    if filter_date_str:
        try:
            fd = date_type.fromisoformat(filter_date_str)
            day_of_week = DAYS[fd.weekday()]
        except ValueError:
            filter_date_str = None

    extra_conds = []
    extra_params = []

    if filter_city:
        extra_conds.append("city ILIKE %s")
        extra_params.append(filter_city)

    if filter_street:
        extra_conds.append("street ILIKE %s")
        extra_params.append(f'%{filter_street}%')

    if day_of_week:
        wh_parts = ["wh.building_id = buildings.id", "wh.day_of_week = %s", "NOT wh.is_closed"]
        wh_params = [day_of_week]
        if filter_time_from:
            wh_parts.append("wh.open_time <= %s::time")
            wh_params.append(filter_time_from)
        if filter_time_to:
            wh_parts.append("wh.close_time >= %s::time")
            wh_params.append(filter_time_to)
        extra_conds.append(f"EXISTS (SELECT 1 FROM working_hours wh WHERE {' AND '.join(wh_parts)})")
        extra_params.extend(wh_params)

    extra_where = (' AND ' + ' AND '.join(extra_conds)) if extra_conds else ''

    with get_db_cursor() as cur:
        cur.execute(f"""
            WITH global_perm AS (
                SELECT EXISTS (
                    SELECT 1
                    FROM user_permissions
                    WHERE user_id = %s
                      AND permission = 'VIEW'
                      AND building_id IS NULL
                      AND room_id IS NULL
                ) AS has_global
            )
            SELECT id, city, street, description
            FROM buildings
            WHERE (
                (SELECT has_global FROM global_perm)
                OR id IN (
                    SELECT building_id
                    FROM user_permissions
                    WHERE user_id = %s
                      AND permission = 'VIEW'
                      AND building_id IS NOT NULL
                      AND room_id IS NULL
                )
            ){extra_where}
            ORDER BY id
        """, [user_id, user_id] + extra_params)
        buildings = cur.fetchall()

        building_ids = [b['id'] for b in buildings]
        working_hours_map = {}
        if building_ids:
            cur.execute("""
                SELECT building_id, day_of_week, open_time, close_time, is_closed
                FROM working_hours
                WHERE building_id = ANY(%s)
            """, (building_ids,))
            for row in cur.fetchall():
                bid = row['building_id']
                if bid not in working_hours_map:
                    working_hours_map[bid] = {}
                working_hours_map[bid][row['day_of_week']] = {
                    'open_time': row['open_time'],
                    'close_time': row['close_time'],
                    'is_closed': row['is_closed']
                }

    time_qs_params = {k: v for k, v in {
        'date': filter_date_str,
        'time_from': filter_time_from,
        'time_to': filter_time_to,
    }.items() if v}
    time_qs = ('?' + urlencode(time_qs_params)) if time_qs_params else ''

    can_grant_view = bool(user_id != 2 and check_granting(user_id, VIEW))

    return render_template(
        'building/browse.html',
        buildings=buildings,
        working_hours_map=working_hours_map,
        days=DAYS,
        filter_city=filter_city or '',
        filter_street=filter_street or '',
        filter_date=filter_date_str or '',
        filter_time_from=filter_time_from or '',
        filter_time_to=filter_time_to or '',
        time_qs=time_qs,
        can_grant_view=can_grant_view,
    )


@building_bp.route('/buildings/new', methods=['GET', 'POST'])
@require_permission(CREATE_BUILDING)
def new_building():
    def render_form():
        return render_template('building/form.html', building=None, days=DAYS,
                               working_hours={}, grantable_permissions=[])

    if request.method == 'POST':
        city = request.form.get('city', '').strip()
        street = request.form.get('street', '').strip()
        description = request.form.get('description', '').strip()

        if not city or not street:
            flash('Город и улица обязательны для заполнения.', 'error')
            return render_form()

        photo = request.files.get('photo')
        photo_error = validate_photo(photo)
        if photo_error:
            flash(photo_error, 'error')
            return render_form()

        try:
            with get_db_cursor(commit=True) as cur:
                building_id = save_building_with_hours(cur, None, city, street, description, request.form)

            if photo and photo.filename:
                save_photo(photo, 'buildings', f'{building_id}.jpeg')

            flash('Здание успешно создано.', 'success')
            return redirect(url_for('building.browse'))
        except Exception as e:
            flash(f'Ошибка при сохранении: {str(e)}', 'error')
            return render_form()

    return render_form()


@building_bp.route('/buildings/<int:id>/edit', methods=['GET', 'POST'])
@require_permission(MANAGE_BUILDING, building_id_arg='id')
def edit_building(id):
    building = get_building(id)
    if not building:
        flash('Здание не найдено.', 'error')
        return redirect(url_for('building.browse'))

    user_id = session.get('user_id')
    grantable_permissions = [
        {'value': p, 'label': l}
        for p, l in _BUILDING_PERM_LABELS
        if check_granting(user_id, p, building_id=id)
    ]

    with get_db_cursor() as cur:
        cur.execute("""
            SELECT u.id as user_id, u.login, u.full_name, up.permission, up.granting
            FROM user_permissions up
            JOIN users u ON u.id = up.user_id
            WHERE up.building_id = %s AND up.room_id IS NULL
            ORDER BY u.login, up.permission
        """, (id,))
        building_permissions = cur.fetchall()

    form_ctx = dict(
        building=building, days=DAYS,
        grantable_permissions=grantable_permissions,
        building_permissions=building_permissions,
        perm_labels=PERMISSION_LABELS,
    )

    def render_form():
        return render_template('building/form.html', working_hours=get_working_hours(id), **form_ctx)

    if request.method == 'POST':
        city = request.form.get('city', '').strip()
        street = request.form.get('street', '').strip()
        description = request.form.get('description', '').strip()

        if not city or not street:
            flash('Город и улица обязательны для заполнения.', 'error')
            return render_form()

        photo = request.files.get('photo')
        photo_error = validate_photo(photo)
        if photo_error:
            flash(photo_error, 'error')
            return render_form()

        try:
            with get_db_cursor(commit=True) as cur:
                save_building_with_hours(cur, id, city, street, description, request.form)

            if photo and photo.filename:
                save_photo(photo, 'buildings', f'{id}.jpeg')

            flash('Здание успешно обновлено.', 'success')
            return redirect(url_for('building.browse'))
        except Exception as e:
            flash(f'Ошибка при сохранении: {str(e)}', 'error')
            return render_form()

    return render_form()


@building_bp.route('/grant-view', methods=['POST'])
@login_required
def grant_global_view():
    user_id = session.get('user_id')

    login = request.form.get('login', '').strip()
    if not login:
        flash('Укажите логин пользователя.', 'error')
        return redirect(url_for('building.browse'))

    with get_db_cursor() as cur:
        cur.execute("SELECT id FROM users WHERE login = %s", (login,))
        target = cur.fetchone()

    if not target:
        flash(f'Пользователь {login} не найден.', 'error')
        return redirect(url_for('building.browse'))

    success = grant_permission(user_id, target['id'], VIEW)
    if success:
        flash(f'Право на просмотр зданий выдано пользователю {login}.', 'success')
    else:
        flash('Не удалось выдать право. Возможно, оно уже выдано или у вас нет прав на это действие.', 'error')
    return redirect(url_for('building.view_permissions'))


@building_bp.route('/buildings/<int:id>/grant', methods=['POST'])
@login_required
def grant_building_permission(id):
    user_id = session.get('user_id')

    building = get_building(id)
    if not building:
        abort(404)

    login = request.form.get('login', '').strip()
    permission = request.form.get('permission', '').strip()

    allowed = {p for p, _ in _BUILDING_PERM_LABELS}
    if not login:
        flash('Укажите логин пользователя.', 'error')
        return redirect(url_for('building.edit_building', id=id))
    if permission not in allowed:
        flash('Недопустимое право.', 'error')
        return redirect(url_for('building.edit_building', id=id))

    with get_db_cursor() as cur:
        cur.execute("SELECT id FROM users WHERE login = %s", (login,))
        target = cur.fetchone()

    if not target:
        flash(f'Пользователь {login} не найден.', 'error')
        return redirect(url_for('building.edit_building', id=id))

    success = grant_permission(user_id, target['id'], permission, building_id=id)
    if success:
        label = next(l for p, l in _BUILDING_PERM_LABELS if p == permission)
        flash(f'Право {label} выдано пользователю {login}.', 'success')
    else:
        flash('Не удалось выдать право. Возможно, оно уже выдано или у вас нет прав на это действие.', 'error')
    return redirect(url_for('building.edit_building', id=id))


@building_bp.route('/permissions/view')
@login_required
def view_permissions():
    user_id = session.get('user_id')
    if not check_granting(user_id, VIEW):
        abort(403)
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT u.id as user_id, u.login, u.full_name, up.granting
            FROM user_permissions up
            JOIN users u ON u.id = up.user_id
            WHERE up.permission = 'VIEW' AND up.building_id IS NULL AND up.room_id IS NULL
            ORDER BY u.login
        """)
        view_holders = cur.fetchall()
    return render_template('building/view_permissions.html', view_holders=view_holders)


@building_bp.route('/revoke-view', methods=['POST'])
@login_required
def revoke_global_view():
    user_id = session.get('user_id')
    target_user_id = request.form.get('target_user_id', type=int)
    if not target_user_id:
        flash('Некорректные данные.', 'error')
        return redirect(url_for('building.view_permissions'))
    success = revoke_permission(user_id, target_user_id, VIEW)
    if success:
        flash('Право на просмотр зданий изъято.', 'success')
    else:
        flash('Не удалось изъять право.', 'error')
    return redirect(url_for('building.view_permissions'))


@building_bp.route('/buildings/<int:id>/revoke', methods=['POST'])
@login_required
def revoke_building_permission(id):
    user_id = session.get('user_id')
    if not get_building(id):
        abort(404)
    target_user_id = request.form.get('target_user_id', type=int)
    permission = request.form.get('permission', '').strip()
    allowed = {p for p, _ in _BUILDING_PERM_LABELS}
    if not target_user_id or permission not in allowed:
        flash('Некорректные данные.', 'error')
        return redirect(url_for('building.edit_building', id=id))
    success = revoke_permission(user_id, target_user_id, permission, building_id=id)
    if success:
        flash('Право изъято.', 'success')
    else:
        flash('Не удалось изъять право.', 'error')
    return redirect(url_for('building.edit_building', id=id))


@building_bp.route('/buildings/<int:id>/delete', methods=['GET', 'POST'])
@require_permission(MANAGE_BUILDING, building_id_arg='id')
def delete_building(id):
    building = get_building(id)
    if not building:
        flash('Здание не найдено.', 'error')
        return redirect(url_for('building.browse'))

    if request.method == 'POST':
        try:
            with get_db_cursor(commit=True) as cur:
                cur.execute("DELETE FROM buildings WHERE id = %s", (id,))
            flash('Здание удалено.', 'success')
        except Exception as e:
            flash(f'Ошибка при удалении: {str(e)}', 'error')
        return redirect(url_for('building.browse'))
    else:
        return render_template('building/confirm_delete.html', building=building)
