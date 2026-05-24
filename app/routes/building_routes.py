from datetime import date as date_type
from urllib.parse import urlencode

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.assets_manager import MAX_PHOTO_SIZE, allowed_file, save_photo
from app.db import get_db_cursor, DAYS

building_bp = Blueprint('building', __name__, url_prefix='/')


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
    )


@building_bp.route('/buildings/new', methods=['GET', 'POST'])
def new_building():
    if request.method == 'POST':
        city = request.form.get('city', '').strip()
        street = request.form.get('street', '').strip()
        description = request.form.get('description', '').strip()

        if not city or not street:
            flash('Город и улица обязательны для заполнения.', 'error')
            return render_template('building/form.html', building=None, days=DAYS, working_hours={})

        photo = request.files.get('photo')
        if photo and photo.filename:
            if not allowed_file(photo.filename):
                flash('Недопустимый формат файла. Разрешены JPEG, PNG, WebP.', 'error')
                return render_template('building/form.html', building=None, days=DAYS, working_hours={})
            if photo.content_length and photo.content_length > MAX_PHOTO_SIZE:
                flash(f'Файл слишком большой. Максимальный размер: {MAX_PHOTO_SIZE // (1024 * 1024)} МБ.', 'error')
                return render_template('building/form.html', building=None, days=DAYS, working_hours={})

        try:
            with get_db_cursor(commit=True) as cur:
                building_id = save_building_with_hours(cur, None, city, street, description, request.form)

            if photo and photo.filename:
                save_photo(photo, 'buildings', f'{building_id}.jpeg')

            flash('Здание успешно создано.', 'success')
            return redirect(url_for('building.browse'))
        except Exception as e:
            flash(f'Ошибка при сохранении: {str(e)}', 'error')
            return render_template('building/form.html', building=None, days=DAYS, working_hours={})
    else:
        return render_template('building/form.html', building=None, days=DAYS, working_hours={})


@building_bp.route('/buildings/<int:id>/edit', methods=['GET', 'POST'])
def edit_building(id):
    building = get_building(id)
    if not building:
        flash('Здание не найдено.', 'error')
        return redirect(url_for('building.browse'))

    if request.method == 'POST':
        city = request.form.get('city', '').strip()
        street = request.form.get('street', '').strip()
        description = request.form.get('description', '').strip()

        if not city or not street:
            flash('Город и улица обязательны для заполнения.', 'error')
            current_hours = get_working_hours(id)
            return render_template('building/form.html', building=building, days=DAYS, working_hours=current_hours)

        photo = request.files.get('photo')
        if photo and photo.filename:
            if not allowed_file(photo.filename):
                flash('Недопустимый формат файла. Разрешены JPEG, PNG, WebP.', 'error')
                current_hours = get_working_hours(id)
                return render_template('building/form.html', building=building, days=DAYS, working_hours=current_hours)
            if photo.content_length and photo.content_length > MAX_PHOTO_SIZE:
                flash(f'Файл слишком большой. Максимальный размер: {MAX_PHOTO_SIZE // (1024 * 1024)} МБ.', 'error')
                current_hours = get_working_hours(id)
                return render_template('building/form.html', building=building, days=DAYS, working_hours=current_hours)

        try:
            with get_db_cursor(commit=True) as cur:
                save_building_with_hours(cur, id, city, street, description, request.form)

            if photo and photo.filename:
                save_photo(photo, 'buildings', f'{id}.jpeg')

            flash('Здание успешно обновлено.', 'success')
            return redirect(url_for('building.browse'))
        except Exception as e:
            flash(f'Ошибка при сохранении: {str(e)}', 'error')
            current_hours = get_working_hours(id)
            return render_template('building/form.html', building=building, days=DAYS, working_hours=current_hours)
    else:
        current_hours = get_working_hours(id)
        return render_template('building/form.html', building=building, days=DAYS, working_hours=current_hours)


@building_bp.route('/buildings/<int:id>/delete', methods=['GET', 'POST'])
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
