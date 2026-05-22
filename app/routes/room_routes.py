from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session

from app.assets_manager import save_photo, allowed_file, MAX_PHOTO_SIZE
from app.db import get_db_cursor, DAYS

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

        cur.execute("""
            SELECT day_of_week, open_time, close_time, is_closed
            FROM working_hours
            WHERE building_id = %s
        """, (building_id,))
        working_hours = {}
        for row in cur.fetchall():
            working_hours[row['day_of_week']] = {
                'open_time': row['open_time'],
                'close_time': row['close_time'],
                'is_closed': row['is_closed']
            }

    return render_template('room/browse.html', building=building, rooms=rooms, working_hours=working_hours, days=DAYS)


@room_bp.route('/buildings/<int:building_id>/rooms/new', methods=['GET', 'POST'])
def new_room(building_id):
    with get_db_cursor() as cur:
        cur.execute("SELECT id, city, street FROM buildings WHERE id = %s", (building_id,))
        building = cur.fetchone()
        if not building:
            abort(404)

        cur.execute("SELECT id, name FROM amenities ORDER BY name")
        all_amenities = cur.fetchall()

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            is_available = request.form.get('is_available') == 'on'
            auto_booking = request.form.get('auto_booking') == 'on'
            size = request.form.get('size')
            capacity = request.form.get('capacity')
            selected_amenity_ids = request.form.getlist('amenity_ids')
            new_amenity_names = [n.strip().lower() for n in request.form.get('new_amenities', '').split(',') if n.strip()]

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
                return render_template('room/form.html', building=building, room=None, all_amenities=all_amenities, room_amenity_ids=set())

            photo = request.files.get('photo')
            if photo and photo.filename:
                if not allowed_file(photo.filename):
                    flash('Недопустимый формат файла. Разрешены JPEG, PNG, WebP.', 'error')
                    return render_template('room/form.html', building=building, room=None, all_amenities=all_amenities, room_amenity_ids=set())
                if photo.content_length and photo.content_length > MAX_PHOTO_SIZE:
                    flash(f'Файл слишком большой. Максимальный размер: {MAX_PHOTO_SIZE // (1024*1024)} МБ.', 'error')
                    return render_template('room/form.html', building=building, room=None, all_amenities=all_amenities, room_amenity_ids=set())

            try:
                with get_db_cursor(commit=True) as cur2:
                    cur2.execute("""
                        INSERT INTO rooms (building_id, name, description, is_available_for_booking, auto_booking, size, capacity)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (building_id, name, description, is_available, auto_booking, size, capacity))
                    room_id = cur2.fetchone()['id']

                    amenity_ids_to_add = [int(x) for x in selected_amenity_ids if x]
                    for amenity_name in new_amenity_names:
                        cur2.execute("""
                            INSERT INTO amenities (name) VALUES (%s)
                            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                            RETURNING id
                        """, (amenity_name,))
                        amenity_ids_to_add.append(cur2.fetchone()['id'])

                    for amenity_id in amenity_ids_to_add:
                        cur2.execute("""
                            INSERT INTO room_amenities (room_id, amenity_id) VALUES (%s, %s)
                            ON CONFLICT DO NOTHING
                        """, (room_id, amenity_id))

                if photo and photo.filename:
                    save_photo(photo, 'rooms', f'{room_id}.jpeg')

                flash('Комната успешно добавлена.', 'success')
                return redirect(url_for('room.browse', building_id=building_id))
            except Exception as e:
                if 'unique constraint' in str(e).lower() or 'duplicate' in str(e).lower():
                    flash('Комната с таким названием уже существует в этом здании.', 'error')
                else:
                    flash(f'Ошибка при добавлении: {e}', 'error')
                return render_template('room/form.html', building=building, room=None, all_amenities=all_amenities, room_amenity_ids=set())

    return render_template('room/form.html', building=building, room=None, all_amenities=all_amenities, room_amenity_ids=set())


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

        cur.execute("SELECT id, name FROM amenities ORDER BY name")
        all_amenities = cur.fetchall()

        cur.execute("SELECT amenity_id FROM room_amenities WHERE room_id = %s", (id,))
        room_amenity_ids = {row['amenity_id'] for row in cur.fetchall()}

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            is_available = request.form.get('is_available') == 'on'
            auto_booking = request.form.get('auto_booking') == 'on'
            size = request.form.get('size')
            capacity = request.form.get('capacity')
            selected_amenity_ids = request.form.getlist('amenity_ids')
            new_amenity_names = [n.strip().lower() for n in request.form.get('new_amenities', '').split(',') if n.strip()]

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
                return render_template('room/form.html', building=room, room=room, all_amenities=all_amenities, room_amenity_ids=room_amenity_ids)

            photo = request.files.get('photo')
            if photo and photo.filename:
                if not allowed_file(photo.filename):
                    flash('Недопустимый формат файла. Разрешены JPEG, PNG, WebP.', 'error')
                    return render_template('room/form.html', building=room, room=room, all_amenities=all_amenities, room_amenity_ids=room_amenity_ids)
                if photo.content_length and photo.content_length > MAX_PHOTO_SIZE:
                    flash(f'Файл слишком большой. Максимальный размер: {MAX_PHOTO_SIZE // (1024*1024)} МБ.', 'error')
                    return render_template('room/form.html', building=room, room=room, all_amenities=all_amenities, room_amenity_ids=room_amenity_ids)

            try:
                with get_db_cursor(commit=True) as cur2:
                    cur2.execute("""
                        UPDATE rooms
                        SET name = %s, description = %s, is_available_for_booking = %s,
                            size = %s, capacity = %s, auto_booking = %s
                        WHERE id = %s
                    """, (name, description, is_available, size, capacity, auto_booking, id))

                    amenity_ids_to_add = [int(x) for x in selected_amenity_ids if x]
                    for amenity_name in new_amenity_names:
                        cur2.execute("""
                            INSERT INTO amenities (name) VALUES (%s)
                            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                            RETURNING id
                        """, (amenity_name,))
                        amenity_ids_to_add.append(cur2.fetchone()['id'])

                    cur2.execute("DELETE FROM room_amenities WHERE room_id = %s", (id,))
                    for amenity_id in amenity_ids_to_add:
                        cur2.execute("""
                            INSERT INTO room_amenities (room_id, amenity_id) VALUES (%s, %s)
                            ON CONFLICT DO NOTHING
                        """, (id, amenity_id))

                if photo and photo.filename:
                    save_photo(photo, 'rooms', f'{id}.jpeg')

                flash('Комната успешно обновлена.', 'success')
                return redirect(url_for('room.browse', building_id=room['building_id']))
            except Exception as e:
                if 'unique constraint' in str(e).lower() or 'duplicate' in str(e).lower():
                    flash('Комната с таким названием уже существует в этом здании.', 'error')
                else:
                    flash(f'Ошибка при обновлении: {e}', 'error')
                return render_template('room/form.html', building=room, room=room, all_amenities=all_amenities, room_amenity_ids=room_amenity_ids)

    return render_template('room/form.html', building=room, room=room, all_amenities=all_amenities, room_amenity_ids=room_amenity_ids)


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

@room_bp.route('/rooms/<int:id>')
def view_room(id):
    user_id = session.get('user_id')
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

        cur.execute("""
            SELECT a.name FROM amenities a
            JOIN room_amenities ra ON a.id = ra.amenity_id
            WHERE ra.room_id = %s
        """, (id,))
        amenities = [row['name'] for row in cur.fetchall()]

        can_review = False
        if user_id:
            cur.execute("""
                SELECT 1 FROM bookings
                WHERE room_id = %s
                  AND booking_user_id = %s
                  AND is_accepted = TRUE
                  AND exit_time < NOW()
                  AND NOT EXISTS (
                      SELECT 1 FROM reviews
                      WHERE room_id = bookings.room_id
                        AND user_id = bookings.booking_user_id
                  )
                LIMIT 1
            """, (id, user_id))
            can_review = cur.fetchone() is not None

        cur.execute("""
            SELECT rv.user_id, rv.room_id, rv.rating, rv.review_text,
                   rv.created_at, rv.updated_at,
                   u.full_name as user_name
            FROM reviews rv
            JOIN users u ON rv.user_id = u.id
            WHERE rv.room_id = %s
            ORDER BY rv.created_at DESC
        """, (id,))
        all_reviews = cur.fetchall()

        user_review = None
        other_reviews = []
        for review in all_reviews:
            if user_id and review['user_id'] == user_id:
                user_review = review
            else:
                other_reviews.append(review)

        cur.execute("SELECT AVG(rating) as avg_rating FROM reviews WHERE room_id = %s", (id,))
        avg_row = cur.fetchone()
        average_rating = round(avg_row['avg_rating'], 1) if avg_row['avg_rating'] else None

        edit_review = request.args.get('edit_review') == '1' and user_review is not None

    return render_template('room/view.html',
                           room=room,
                           building=room,
                           amenities=amenities,
                           reviews=other_reviews,
                           user_review=user_review,
                           can_review=can_review,
                           average_rating=average_rating,
                           edit_review=edit_review)


@room_bp.route('/rooms/<int:id>/review', methods=['POST'])
def create_review(id):
    user_id = session.get('user_id')
    if not user_id:
        flash('Необходимо войти в систему.', 'error')
        return redirect(url_for('room.view_room', id=id))

    rating_str = request.form.get('rating', '').strip()
    review_text = request.form.get('review_text', '').strip()[:1000]

    try:
        rating = int(rating_str)
        if rating < 1 or rating > 10:
            raise ValueError
    except ValueError:
        flash('Оценка должна быть целым числом от 1 до 10.', 'error')
        return redirect(url_for('room.view_room', id=id))

    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            SELECT 1 FROM bookings
            WHERE room_id = %s
              AND booking_user_id = %s
              AND is_accepted = TRUE
              AND exit_time < NOW()
              AND NOT EXISTS (
                  SELECT 1 FROM reviews
                  WHERE room_id = bookings.room_id
                    AND user_id = bookings.booking_user_id
              )
            LIMIT 1
        """, (id, user_id))
        if not cur.fetchone():
            flash('Вы не можете оставить отзыв (нет завершённой брони или отзыв уже существует).', 'error')
            return redirect(url_for('room.view_room', id=id))

        cur.execute("SELECT 1 FROM reviews WHERE user_id = %s AND room_id = %s", (user_id, id))
        if cur.fetchone():
            flash('Вы уже оставили отзыв на эту комнату.', 'error')
            return redirect(url_for('room.view_room', id=id))

        cur.execute("""
            INSERT INTO reviews (user_id, room_id, rating, review_text)
            VALUES (%s, %s, %s, %s)
        """, (user_id, id, rating, review_text))

    flash('Отзыв успешно добавлен.', 'success')
    return redirect(url_for('room.view_room', id=id))


@room_bp.route('/rooms/<int:id>/review/edit', methods=['POST'])
def edit_review(id):
    user_id = session.get('user_id')
    if not user_id:
        flash('Необходимо войти в систему.', 'error')
        return redirect(url_for('room.view_room', id=id))

    rating_str = request.form.get('rating', '').strip()
    review_text = request.form.get('review_text', '').strip()[:1000]

    try:
        rating = int(rating_str)
        if rating < 1 or rating > 10:
            raise ValueError
    except ValueError:
        flash('Оценка должна быть целым числом от 1 до 10.', 'error')
        return redirect(url_for('room.view_room', id=id))

    with get_db_cursor(commit=True) as cur:
        cur.execute("SELECT 1 FROM reviews WHERE user_id = %s AND room_id = %s", (user_id, id))
        if not cur.fetchone():
            flash('Отзыв не найден.', 'error')
            return redirect(url_for('room.view_room', id=id))

        cur.execute("""
            UPDATE reviews
            SET rating = %s, review_text = %s, updated_at = NOW()
            WHERE user_id = %s AND room_id = %s
        """, (rating, review_text, user_id, id))

    flash('Отзыв обновлён.', 'success')
    return redirect(url_for('room.view_room', id=id))


@room_bp.route('/rooms/<int:id>/review/delete', methods=['POST'])
def delete_review(id):
    user_id = session.get('user_id')
    if not user_id:
        flash('Необходимо войти в систему.', 'error')
        return redirect(url_for('room.view_room', id=id))

    with get_db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM reviews WHERE user_id = %s AND room_id = %s", (user_id, id))
        if cur.rowcount == 0:
            flash('Отзыв не найден или уже удалён.', 'error')

    flash('Отзыв удалён.', 'success')
    return redirect(url_for('room.view_room', id=id))
