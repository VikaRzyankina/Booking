from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from app.db import get_db_cursor

room_bp = Blueprint('room', __name__, url_prefix='/')


@room_bp.route('/buildings/<int:building_id>/browse')
def browse(building_id):
    with get_db_cursor() as cur:
        cur.execute("SELECT id, city, street FROM buildings WHERE id = %s", (building_id,))
        building = cur.fetchone()
        if not building:
            abort(404)

        cur.execute("""
            SELECT id, name, description, is_available_for_booking, size, capacity
            FROM rooms
            WHERE building_id = %s
            ORDER BY id
        """, (building_id,))
        rooms = cur.fetchall()

    return render_template('room/browse.html', building=building, rooms=rooms)


@room_bp.route('/buildings/<int:building_id>/rooms/new', methods=['GET', 'POST'])
def new_room(building_id):
    with get_db_cursor() as cur:
        cur.execute("SELECT id, city, street FROM buildings WHERE id = %s", (building_id,))
        building = cur.fetchone()
        if not building:
            abort(404)

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            is_available = request.form.get('is_available') == 'on'
            auto_booking = request.form.get('auto_booking') == 'on'
            size = request.form.get('size')
            capacity = request.form.get('capacity')

            error = None
            try:
                if not name:
                    error = "Название комнаты обязательно."
                elif not capacity or int(capacity) <= 0:
                    error = "Вместимость должна быть положительным числом."
                elif size and float(size) < 0:
                    error = "Размер не может быть отрицательным."
            except ValueError:
                error = "Проверьте правильность введённых чисел."

            if error:
                flash(error, 'error')
                return render_template('room/form.html', building=building, room=None)

            try:
                with get_db_cursor(commit=True) as cur2:
                    cur2.execute("""
                        INSERT INTO rooms (building_id, name, description, is_available_for_booking, auto_booking, size, capacity)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (building_id, name, description, is_available, auto_booking, size, capacity))
                flash('Комната успешно добавлена.', 'success')
                return redirect(url_for('room.browse', building_id=building_id))
            except Exception as e:
                if 'unique constraint' in str(e).lower() or 'duplicate' in str(e).lower():
                    flash('Комната с таким названием уже существует в этом здании.', 'error')
                else:
                    flash(f'Ошибка при добавлении: {e}', 'error')
                return render_template('room/form.html', building=building, room=None)

    return render_template('room/form.html', building=building, room=None)


@room_bp.route('/rooms/<int:id>/edit', methods=['GET', 'POST'])
def edit_room(id):
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT r.*, b.id as building_id, b.city, b.street
            FROM rooms r
            JOIN buildings b ON r.building_id = b.id
            WHERE r.id = %s
        """, (id,))
        room = cur.fetchone()
        if not room:
            abort(404)

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            is_available = request.form.get('is_available') == 'on'
            auto_booking = request.form.get('auto_booking') == 'on'
            size = request.form.get('size')
            capacity = request.form.get('capacity')

            error = None
            try:
                if not name:
                    error = "Название комнаты обязательно."
                elif not capacity or int(capacity) <= 0:
                    error = "Вместимость должна быть положительным числом."
                elif size and float(size) < 0:
                    error = "Размер не может быть отрицательным."
            except ValueError:
                error = "Проверьте правильность введённых чисел."

            if error:
                flash(error, 'error')
                return render_template('room/form.html', building=room, room=room)

            try:
                with get_db_cursor(commit=True) as cur2:
                    cur2.execute("""
                        UPDATE rooms
                        SET name = %s, description = %s, is_available_for_booking = %s, 
                            size = %s, capacity = %s, auto_booking = %s
                        WHERE id = %s
                    """, (name, description, is_available, size, capacity, auto_booking, id))
                flash('Комната успешно обновлена.', 'success')
                return redirect(url_for('room.browse', building_id=room['building_id']))
            except Exception as e:
                if 'unique constraint' in str(e).lower() or 'duplicate' in str(e).lower():
                    flash('Комната с таким названием уже существует в этом здании.', 'error')
                else:
                    flash(f'Ошибка при обновлении: {e}', 'error')
                return render_template('room/form.html', building=room, room=room)

    return render_template('room/form.html', building=room, room=room)


@room_bp.route('/rooms/<int:id>/delete', methods=['POST'])
def delete_room(id):
    with get_db_cursor() as cur:
        cur.execute("SELECT building_id FROM rooms WHERE id = %s", (id,))
        room = cur.fetchone()
        if not room:
            abort(404)
        building_id = room['building_id']

    with get_db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM rooms WHERE id = %s", (id,))

    flash('Комната удалена.', 'success')
    return redirect(url_for('room.browse', building_id=building_id))
