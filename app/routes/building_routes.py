from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app.db import get_db_cursor

building_bp = Blueprint('building', __name__, url_prefix='/')

DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


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

    with get_db_cursor() as cur:
        cur.execute("""
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
            WHERE (SELECT has_global FROM global_perm)
               OR id IN (
                    SELECT building_id
                    FROM user_permissions
                    WHERE user_id = %s
                      AND permission = 'VIEW'
                      AND building_id IS NOT NULL
                      AND room_id IS NULL
            )
            ORDER BY id
        """, (user_id, user_id))
        buildings = cur.fetchall()

    return render_template('building/browse.html', buildings=buildings)


@building_bp.route('/buildings/new', methods=['GET', 'POST'])
def new_building():
    if request.method == 'POST':
        city = request.form.get('city', '').strip()
        street = request.form.get('street', '').strip()
        description = request.form.get('description', '').strip()

        if not city or not street:
            flash('Город и улица обязательны для заполнения.', 'error')
            return render_template('building/form.html', building=None, days=DAYS, working_hours={})

        try:
            with get_db_cursor(commit=True) as cur:
                save_building_with_hours(cur, None, city, street, description, request.form)
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

        try:
            with get_db_cursor(commit=True) as cur:
                save_building_with_hours(cur, id, city, street, description, request.form)
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
