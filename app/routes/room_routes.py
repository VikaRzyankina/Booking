from datetime import datetime as dt_type
from urllib.parse import urlencode

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session

from app.assets_manager import save_photo, validate_photo
from app.db import get_db_cursor, DAYS, TZ, RATING_MIN_VOTES
from app.permissions import (check_permission, require_permission, login_required, grant_permission,
                             check_granting, revoke_permission, PERMISSION_LABELS,
                             VIEW, CREATE_ROOM, MANAGE_ROOM, MANAGE_BOOKING_REQUESTS, REQUEST_BOOKING)
from app.routes.building_routes import get_working_hours

room_bp = Blueprint('room', __name__, url_prefix='/')

_ROOM_PERM_LABELS = [(p, PERMISSION_LABELS[p]) for p in [VIEW, MANAGE_ROOM, REQUEST_BOOKING, MANAGE_BOOKING_REQUESTS]]


def _validate_room_form(name, capacity, size):
    try:
        if not name:
            return "Название комнаты обязательно."
        if not capacity or int(capacity) <= 0:
            return "Вместимость должна быть положительным числом."
        if size and float(size) < 0:
            return "Размер не может быть отрицательным."
    except ValueError:
        return "Проверьте правильность введённых чисел."
    return None


def _parse_rating(rating_str):
    try:
        rating = int(rating_str)
        if rating < 1 or rating > 10:
            raise ValueError
        return rating, None
    except ValueError:
        return None, 'Оценка должна быть целым числом от 1 до 10.'


def _resolve_amenity_ids(cur, selected_ids, new_names):
    ids = [int(x) for x in selected_ids if x]
    for name in new_names:
        cur.execute("""
            INSERT INTO amenities (name) VALUES (%s)
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
        """, (name,))
        ids.append(cur.fetchone()['id'])
    return ids


@room_bp.route('/buildings/<int:building_id>/browse')
def browse(building_id):
    user_id = session.get('user_id', 2)
    if not check_permission(user_id, VIEW, building_id=building_id):
        abort(403)

    filter_date_str = request.args.get('date', '').strip() or None
    filter_time_from = request.args.get('time_from', '').strip() or None
    filter_time_to = request.args.get('time_to', '').strip() or None
    filter_amenity_ids = request.args.getlist('amenity_ids', type=int)
    filter_size_min = request.args.get('size_min', '').strip() or None
    filter_size_max = request.args.get('size_max', '').strip() or None
    filter_capacity_min = request.args.get('capacity_min', '').strip() or None

    entry_time = exit_time = None
    if filter_date_str and filter_time_from and filter_time_to:
        try:
            entry_time = dt_type.fromisoformat(f"{filter_date_str}T{filter_time_from}").replace(tzinfo=TZ)
            exit_time = dt_type.fromisoformat(f"{filter_date_str}T{filter_time_to}").replace(tzinfo=TZ)
            if exit_time <= entry_time:
                entry_time = exit_time = None
        except ValueError:
            pass

    extra_conds = []
    extra_params = []

    if entry_time and exit_time:
        extra_conds.append("""NOT EXISTS (
            SELECT 1 FROM bookings bk
            WHERE bk.room_id = r.id
              AND bk.is_accepted = TRUE
              AND bk.entry_time < %s
              AND bk.exit_time > %s
        )""")
        extra_params.extend([exit_time, entry_time])

    if filter_amenity_ids:
        extra_conds.append("""(
            SELECT COUNT(*) FROM room_amenities ra
            WHERE ra.room_id = r.id AND ra.amenity_id = ANY(%s)
        ) = %s""")
        extra_params.extend([filter_amenity_ids, len(filter_amenity_ids)])

    try:
        if filter_size_min:
            extra_conds.append("r.size >= %s")
            extra_params.append(float(filter_size_min))
        if filter_size_max:
            extra_conds.append("r.size <= %s")
            extra_params.append(float(filter_size_max))
        if filter_capacity_min:
            extra_conds.append("r.capacity >= %s")
            extra_params.append(int(filter_capacity_min))
    except (ValueError, TypeError):
        pass

    extra_where = (' AND ' + ' AND '.join(extra_conds)) if extra_conds else ''

    with get_db_cursor() as cur:
        cur.execute("SELECT id, city, street FROM buildings WHERE id = %s", (building_id,))
        building = cur.fetchone()
        if not building:
            abort(404)

        cur.execute(f"""
            WITH view_scope AS (
                SELECT
                    EXISTS (
                        SELECT 1 FROM user_permissions
                        WHERE user_id = %s AND permission = 'VIEW'
                          AND building_id IS NULL AND room_id IS NULL
                    ) AS has_global,
                    EXISTS (
                        SELECT 1 FROM user_permissions
                        WHERE user_id = %s AND permission = 'VIEW'
                          AND building_id = %s AND room_id IS NULL
                    ) AS has_building
            )
            SELECT r.id, r.name, r.description, r.is_available_for_booking, r.size, r.capacity
            FROM rooms r
            WHERE r.building_id = %s
              AND (
                  (SELECT has_global FROM view_scope)
                  OR (SELECT has_building FROM view_scope)
                  OR EXISTS (
                      SELECT 1 FROM user_permissions
                      WHERE user_id = %s AND permission = 'VIEW'
                        AND building_id = %s AND room_id = r.id
                  )
              ){extra_where}
            ORDER BY r.id
        """, [user_id, user_id, building_id, building_id, user_id, building_id] + extra_params)
        rooms = cur.fetchall()

        cur.execute("SELECT id, name FROM amenities ORDER BY name")
        all_amenities = cur.fetchall()

        room_ids = [r['id'] for r in rooms]
        ratings_map = {}
        if room_ids:
            cur.execute("""
                WITH global_avg AS (
                    SELECT COALESCE(AVG(rating), 0) AS c FROM reviews
                ),
                room_stats AS (
                    SELECT room_id, COUNT(*) AS v, AVG(rating) AS r_avg
                    FROM reviews
                    WHERE room_id = ANY(%s)
                    GROUP BY room_id
                )
                SELECT
                    rs.room_id,
                    ROUND((
                        (rs.v::float / (rs.v + %s)) * rs.r_avg +
                        (%s::float / (rs.v + %s)) * ga.c
                    )::numeric, 1) AS wr
                FROM room_stats rs, global_avg ga
            """, (room_ids, RATING_MIN_VOTES, RATING_MIN_VOTES, RATING_MIN_VOTES))
            for row in cur.fetchall():
                ratings_map[row['room_id']] = float(row['wr'])

    working_hours = get_working_hours(building_id)

    time_qs_params = {k: v for k, v in {
        'date': filter_date_str,
        'time_from': filter_time_from,
        'time_to': filter_time_to,
    }.items() if v}
    time_qs = ('?' + urlencode(time_qs_params)) if time_qs_params else ''

    return render_template(
        'room/browse.html',
        building=building,
        rooms=rooms,
        ratings_map=ratings_map,
        working_hours=working_hours,
        days=DAYS,
        all_amenities=all_amenities,
        filter_date=filter_date_str or '',
        filter_time_from=filter_time_from or '',
        filter_time_to=filter_time_to or '',
        filter_amenity_ids=filter_amenity_ids,
        filter_size_min=filter_size_min or '',
        filter_size_max=filter_size_max or '',
        filter_capacity_min=filter_capacity_min or '',
        time_qs=time_qs,
    )


@room_bp.route('/buildings/<int:building_id>/rooms/new', methods=['GET', 'POST'])
@require_permission(CREATE_ROOM, building_id_arg='building_id')
def new_room(building_id):
    with get_db_cursor() as cur:
        cur.execute("SELECT id, city, street FROM buildings WHERE id = %s", (building_id,))
        building = cur.fetchone()
        if not building:
            abort(404)
        cur.execute("SELECT id, name FROM amenities ORDER BY name")
        all_amenities = cur.fetchall()

    def render_form():
        return render_template('room/form.html', building=building, room=None,
                               all_amenities=all_amenities, room_amenity_ids=set(),
                               grantable_permissions=[])

    if request.method == 'GET':
        return render_form()

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    is_available = request.form.get('is_available') == 'on'
    auto_booking = request.form.get('auto_booking') == 'on'
    size = request.form.get('size')
    capacity = request.form.get('capacity')
    selected_amenity_ids = request.form.getlist('amenity_ids')
    new_amenity_names = [n.strip().lower() for n in request.form.get('new_amenities', '').split(',') if n.strip()]

    error = _validate_room_form(name, capacity, size)
    if error:
        flash(error, 'error')
        return render_form()

    photo = request.files.get('photo')
    photo_error = validate_photo(photo)
    if photo_error:
        flash(photo_error, 'error')
        return render_form()

    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO rooms (building_id, name, description, is_available_for_booking, auto_booking, size, capacity)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (building_id, name, description, is_available, auto_booking, size, capacity))
            room_id = cur.fetchone()['id']

            for amenity_id in _resolve_amenity_ids(cur, selected_amenity_ids, new_amenity_names):
                cur.execute("""
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
        return render_form()


@room_bp.route('/rooms/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_room(id):
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

        if not check_permission(user_id, MANAGE_ROOM, building_id=room['building_id'], room_id=id):
            abort(403)

        grantable_permissions = [
            {'value': p, 'label': l}
            for p, l in _ROOM_PERM_LABELS
            if check_granting(user_id, p, building_id=room['building_id'], room_id=id)
        ]

        cur.execute("""
            SELECT u.id as user_id, u.login, u.full_name, up.permission, up.granting
            FROM user_permissions up
            JOIN users u ON u.id = up.user_id
            WHERE up.building_id = %s AND up.room_id = %s
            ORDER BY u.login, up.permission
        """, (room['building_id'], id))
        room_permissions = cur.fetchall()

        cur.execute("SELECT id, name FROM amenities ORDER BY name")
        all_amenities = cur.fetchall()

        cur.execute("SELECT amenity_id FROM room_amenities WHERE room_id = %s", (id,))
        room_amenity_ids = {row['amenity_id'] for row in cur.fetchall()}

    form_ctx = dict(
        building=room, room=room,
        all_amenities=all_amenities, room_amenity_ids=room_amenity_ids,
        grantable_permissions=grantable_permissions,
        room_permissions=room_permissions,
        perm_labels=PERMISSION_LABELS,
    )

    def render_form():
        return render_template('room/form.html', **form_ctx)

    if request.method == 'GET':
        return render_form()

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    is_available = request.form.get('is_available') == 'on'
    auto_booking = request.form.get('auto_booking') == 'on'
    size = request.form.get('size')
    capacity = request.form.get('capacity')
    selected_amenity_ids = request.form.getlist('amenity_ids')
    new_amenity_names = [n.strip().lower() for n in request.form.get('new_amenities', '').split(',') if n.strip()]

    error = _validate_room_form(name, capacity, size)
    if error:
        flash(error, 'error')
        return render_form()

    photo = request.files.get('photo')
    photo_error = validate_photo(photo)
    if photo_error:
        flash(photo_error, 'error')
        return render_form()

    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE rooms
                SET name = %s, description = %s, is_available_for_booking = %s,
                    size = %s, capacity = %s, auto_booking = %s
                WHERE id = %s
            """, (name, description, is_available, size, capacity, auto_booking, id))

            cur.execute("DELETE FROM room_amenities WHERE room_id = %s", (id,))
            for amenity_id in _resolve_amenity_ids(cur, selected_amenity_ids, new_amenity_names):
                cur.execute("""
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
        return render_form()


@room_bp.route('/rooms/<int:id>/grant', methods=['POST'])
@login_required
def grant_room_permission(id):
    user_id = session.get('user_id')

    with get_db_cursor() as cur:
        cur.execute("SELECT building_id FROM rooms WHERE id = %s", (id,))
        row = cur.fetchone()

    if not row:
        abort(404)
    building_id = row['building_id']

    login = request.form.get('login', '').strip()
    permission = request.form.get('permission', '').strip()

    allowed = {p for p, _ in _ROOM_PERM_LABELS}
    if not login:
        flash('Укажите логин пользователя.', 'error')
        return redirect(url_for('room.edit_room', id=id))
    if permission not in allowed:
        flash('Недопустимое право.', 'error')
        return redirect(url_for('room.edit_room', id=id))

    with get_db_cursor() as cur:
        cur.execute("SELECT id FROM users WHERE login = %s", (login,))
        target = cur.fetchone()

    if not target:
        flash(f'Пользователь {login} не найден.', 'error')
        return redirect(url_for('room.edit_room', id=id))

    with_granting = request.form.get('with_granting') == 'on'
    success = grant_permission(user_id, target['id'], permission, building_id=building_id, room_id=id, with_granting=with_granting)
    if success:
        label = next(l for p, l in _ROOM_PERM_LABELS if p == permission)
        flash(f'Право {label} выдано пользователю {login}.', 'success')
    else:
        flash('Не удалось выдать право. Возможно, оно уже выдано или у вас нет прав на это действие.', 'error')
    return redirect(url_for('room.edit_room', id=id))


@room_bp.route('/rooms/<int:id>/revoke', methods=['POST'])
@login_required
def revoke_room_permission(id):
    user_id = session.get('user_id')
    with get_db_cursor() as cur:
        cur.execute("SELECT building_id FROM rooms WHERE id = %s", (id,))
        row = cur.fetchone()
    if not row:
        abort(404)
    building_id = row['building_id']
    target_user_id = request.form.get('target_user_id', type=int)
    permission = request.form.get('permission', '').strip()
    allowed = {p for p, _ in _ROOM_PERM_LABELS}
    if not target_user_id or permission not in allowed:
        flash('Некорректные данные.', 'error')
        return redirect(url_for('room.edit_room', id=id))
    success = revoke_permission(user_id, target_user_id, permission, building_id=building_id, room_id=id)
    if success:
        flash('Право изъято.', 'success')
    else:
        flash('Не удалось изъять право.', 'error')
    return redirect(url_for('room.edit_room', id=id))


@room_bp.route('/rooms/<int:id>/delete', methods=['POST'])
@login_required
def delete_room(id):
    user_id = session.get('user_id')

    with get_db_cursor() as cur:
        cur.execute("SELECT building_id FROM rooms WHERE id = %s", (id,))
        room = cur.fetchone()
        if not room:
            abort(404)
        building_id = room['building_id']

    if not check_permission(user_id, MANAGE_ROOM, building_id=building_id, room_id=id):
        abort(403)

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

        cur.execute("""
            SELECT
                COUNT(*) as v,
                AVG(rating) as r_avg,
                (SELECT COALESCE(AVG(rating), 0) FROM reviews) as c
            FROM reviews WHERE room_id = %s
        """, (id,))
        stat = cur.fetchone()
        if stat['v'] > 0:
            m = RATING_MIN_VOTES
            average_rating = round(
                (stat['v'] / (stat['v'] + m)) * float(stat['r_avg']) +
                (m / (stat['v'] + m)) * float(stat['c']),
                1
            )
        else:
            average_rating = None

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
@login_required
def create_review(id):
    user_id = session.get('user_id')

    rating, rating_err = _parse_rating(request.form.get('rating', '').strip())
    if rating_err:
        flash(rating_err, 'error')
        return redirect(url_for('room.view_room', id=id))

    review_text = request.form.get('review_text', '').strip()[:1000]

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
@login_required
def edit_review(id):
    user_id = session.get('user_id')

    rating, rating_err = _parse_rating(request.form.get('rating', '').strip())
    if rating_err:
        flash(rating_err, 'error')
        return redirect(url_for('room.view_room', id=id))

    review_text = request.form.get('review_text', '').strip()[:1000]

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
@login_required
def delete_review(id):
    user_id = session.get('user_id')

    with get_db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM reviews WHERE user_id = %s AND room_id = %s", (user_id, id))
        if cur.rowcount == 0:
            flash('Отзыв не найден или уже удалён.', 'error')

    flash('Отзыв удалён.', 'success')
    return redirect(url_for('room.view_room', id=id))
