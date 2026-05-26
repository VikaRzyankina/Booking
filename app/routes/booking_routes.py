import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, abort

from app.db import get_db_cursor, DAYS
from app.permissions import check_permission, REQUEST_BOOKING
from app.routes.building_routes import get_working_hours

booking_bp = Blueprint('booking', __name__, url_prefix='/')

TZ = ZoneInfo('Europe/Moscow')


def get_building(room_id):
    with get_db_cursor() as cur:
        cur.execute("SELECT building_id FROM rooms WHERE id = %s", (room_id,))
        row = cur.fetchone()
        return row[0] if row else None


def is_available(building_id, room_id, entry_time, exit_time):
    if entry_time >= exit_time:
        return False

    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM bookings WHERE room_id = %s AND is_accepted = TRUE AND entry_time < %s AND exit_time > %s)",
            (room_id, exit_time, entry_time)
        )
        if cursor.fetchone()[0]:
            return False

    working_hours = get_working_hours(building_id)

    current_date = entry_time.date()
    end_date = exit_time.date()
    one_day = timedelta(days=1)

    while current_date <= end_date:
        day_name = DAYS[current_date.weekday()]
        day_start = datetime.combine(current_date, datetime.min.time(), tzinfo=TZ)
        day_end = day_start + one_day

        segment_start = max(entry_time, day_start)
        segment_end = min(exit_time, day_end)

        if segment_start < segment_end:
            if day_name not in working_hours:
                return False

            day_hours = working_hours[day_name]
            if day_hours['is_closed']:
                return False

            open_time = day_hours['open_time']
            close_time = day_hours['close_time']

            opening_datetime = datetime.combine(current_date, open_time, tzinfo=TZ)
            if close_time > open_time:
                closing_datetime = datetime.combine(current_date, close_time, tzinfo=TZ)
            else:
                closing_datetime = datetime.combine(current_date + one_day, close_time, tzinfo=TZ)

            if segment_start < opening_datetime or segment_end > closing_datetime:
                return False

        current_date += one_day

    return True


@booking_bp.route('/booking/<int:room_id>/availability')
def room_availability(room_id):
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    if not year or not month:
        now = datetime.now(TZ)
        year, month = now.year, now.month

    building_id = get_building(room_id)
    first_day = datetime(year, month, 1, tzinfo=TZ)
    last_day = datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59, tzinfo=TZ)

    with get_db_cursor() as cur:
        cur.execute("""
            SELECT entry_time, exit_time
            FROM bookings
            WHERE room_id = %s
              AND is_accepted = TRUE
              AND exit_time > %s
              AND entry_time < %s
            ORDER BY entry_time
        """, (room_id, first_day, last_day))
        rows = cur.fetchall()

    bookings = {}
    for row in rows:
        entry = row['entry_time']
        exit_ = row['exit_time']
        if entry.tzinfo is None:
            entry = entry.replace(tzinfo=TZ)
        else:
            entry = entry.astimezone(TZ)
        if exit_.tzinfo is None:
            exit_ = exit_.replace(tzinfo=TZ)
        else:
            exit_ = exit_.astimezone(TZ)
        day_key = entry.date().isoformat()
        bookings.setdefault(day_key, []).append({
            'entry': entry.strftime('%H:%M'),
            'exit': exit_.strftime('%H:%M'),
        })

    wh_raw = get_working_hours(building_id) if building_id else {}
    working_hours = {}
    for iso_dow, day_name in enumerate(DAYS):
        wh = wh_raw.get(day_name)
        if wh:
            working_hours[str(iso_dow)] = {
                'closed': bool(wh['is_closed']),
                'open': wh['open_time'].strftime('%H:%M') if not wh['is_closed'] else None,
                'close': wh['close_time'].strftime('%H:%M') if not wh['is_closed'] else None,
            }

    return jsonify({'bookings': bookings, 'working_hours': working_hours})


@booking_bp.route('/booking/my')
def my_bookings():
    user_id = session.get('user_id')
    if not user_id:
        flash('Необходима авторизация.', 'error')
        return redirect(url_for('auth.login'))

    now = datetime.now(TZ)
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT
                b.id,
                b.room_id,
                b.entry_time,
                b.exit_time,
                b.is_accepted,
                b.deny_reason,
                b.is_automatic,
                bld.city,
                bld.street
            FROM bookings b
            JOIN rooms r ON r.id = b.room_id
            JOIN buildings bld ON bld.id = r.building_id
            WHERE b.booking_user_id = %s
            ORDER BY b.entry_time DESC
        """, (user_id,))
        bookings = cur.fetchall()

    past = []
    future = []
    for b in bookings:
        if b['exit_time'] <= now:
            past.append(b)
        else:
            future.append(b)

    return render_template('booking/my.html', past_bookings=past, future_bookings=future)


@booking_bp.route('/booking/browse')
def browse():
    user_id = session.get('user_id', 2)
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT
                bookings.*,
                buildings.city,
                buildings.street,
                users.login AS booking_user_login,
                users.full_name AS booking_user_full_name
            FROM bookings
            INNER JOIN rooms ON rooms.id = bookings.room_id
            INNER JOIN buildings ON buildings.id = rooms.building_id
            INNER JOIN users ON users.id = bookings.booking_user_id
            WHERE bookings.is_accepted IS NULL
                AND EXISTS (
                    SELECT 1
                    FROM user_permissions
                    WHERE user_permissions.user_id = %s
                        AND user_permissions.permission = 'MANAGE_BOOKING_REQUESTS'
                        AND COALESCE(user_permissions.building_id, rooms.building_id) = rooms.building_id
                        AND COALESCE(user_permissions.room_id, bookings.room_id) = bookings.room_id
                )
            ORDER BY
                buildings.id,
                bookings.entry_time;
        """, (user_id,))
        requests = cur.fetchall()
    return render_template('booking/browse.html', requests=requests)


def can_manage_booking(user_id, booking_id):
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT 1
                FROM bookings b
                JOIN rooms r ON r.id = b.room_id
                JOIN user_permissions up ON up.user_id = %s
                WHERE b.id = %s
                  AND b.is_accepted IS NULL
                  AND up.permission = 'MANAGE_BOOKING_REQUESTS'
                  AND COALESCE(up.building_id, r.building_id) = r.building_id
                  AND COALESCE(up.room_id, b.room_id) = b.room_id
            )
        """, (user_id, booking_id))
        return cur.fetchone()[0]


@booking_bp.route('/booking/<int:id>/accept', methods=['POST'])
def accept_request(id):
    user_id = session.get('user_id')
    if not user_id:
        flash('Необходима авторизация.', 'error')
        return redirect(url_for('auth.login'))

    if not can_manage_booking(user_id, id):
        flash('У вас нет прав на подтверждение этой заявки.', 'error')
        return redirect(url_for('booking.browse'))

    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE bookings
                SET is_accepted = TRUE,
                    manager_user_id = %s,
                    deny_reason = NULL
                WHERE id = %s AND is_accepted IS NULL
            """, (user_id, id))
            if cur.rowcount == 0:
                flash('Заявка уже обработана или не найдена.', 'error')
            else:
                flash('Заявка успешно подтверждена.', 'success')
    except Exception as e:
        flash(f'Ошибка при подтверждении: {e}', 'error')

    return redirect(url_for('booking.browse'))


@booking_bp.route('/booking/<int:id>/deny', methods=['POST'])
def deny_request(id):
    user_id = session.get('user_id')
    if not user_id:
        flash('Необходима авторизация.', 'error')
        return redirect(url_for('auth.login'))

    if not can_manage_booking(user_id, id):
        flash('У вас нет прав на отклонение этой заявки.', 'error')
        return redirect(url_for('booking.browse'))

    reason = request.form.get('reason', '').strip() or None
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE bookings
                SET is_accepted = FALSE,
                    manager_user_id = %s,
                    deny_reason = %s
                WHERE id = %s AND is_accepted IS NULL
            """, (user_id, reason, id))
            if cur.rowcount == 0:
                flash('Заявка уже обработана или не найдена.', 'error')
            else:
                flash('Заявка отклонена.', 'success')
    except Exception as e:
        flash(f'Ошибка при отклонении: {e}', 'error')
    return redirect(url_for('booking.browse'))


@booking_bp.route('/booking/<int:room_id>/new', methods=['GET', 'POST'])
def booking_request(room_id):
    user_id = session.get('user_id')
    if not user_id:
        flash('Необходима авторизация.', 'error')
        return redirect(url_for('user.login'))

    building_id = get_building(room_id)

    if not building_id:
        flash('Комната не найдена.', 'error')
        return redirect(url_for('building.browse'))

    if not check_permission(user_id, REQUEST_BOOKING, building_id=building_id, room_id=room_id):
        abort(403)

    if request.method == 'POST':
        try:
            booking_start_str = request.form.get('booking_start')
            booking_time_str = request.form.get('booking_time')

            if not booking_start_str or not booking_time_str:
                flash('Пожалуйста, заполните все поля.', 'error')
                return redirect(request.url)

            booking_start = datetime.strptime(booking_start_str, '%Y-%m-%dT%H:%M')
            booking_time = int(booking_time_str)

            if booking_start.minute % 10 != 0:
                flash('Время начала должно быть кратно 10 минутам.', 'error')
                return redirect(request.url)

            if booking_time <= 0 or booking_time % 10 != 0:
                flash('Продолжительность должна быть кратна 10 минутам.', 'error')
                return redirect(request.url)

            entry_time = booking_start.replace(tzinfo=TZ)
            exit_time = entry_time + timedelta(minutes=booking_time)

            if not is_available(building_id, room_id, entry_time, exit_time):
                flash('Комната уже забронирована на выбранное время.', 'error')
                return redirect(request.url)

            with get_db_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO bookings (room_id, booking_user_id, entry_time, exit_time, is_accepted, is_automatic)
                        SELECT %s, %s, %s, %s,
                               CASE WHEN auto_booking THEN TRUE ELSE NULL END,
                               auto_booking
                        FROM rooms
                        WHERE id = %s
                """, (room_id, user_id, entry_time, exit_time, room_id))

            flash('Заявка на бронирование успешно создана.', 'success')
            return redirect(url_for('room.view_room', id=room_id))

        except (ValueError, TypeError) as e:
            flash(f'Ошибка в формате данных: {e}', 'error')
            return redirect(request.url)
        except Exception as e:
            flash(f'Ошибка при сохранении бронирования: {e}', 'error')
            return redirect(request.url)

    wh = get_working_hours(building_id)
    return render_template(
        'booking/form.html',
        room_id=room_id,
        working_hours=wh,
        days=DAYS,
        initial_date=request.args.get('date', ''),
        initial_start=request.args.get('time_from', ''),
        initial_end=request.args.get('time_to', ''),
    )
