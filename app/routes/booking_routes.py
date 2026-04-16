from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from app.db import get_db_cursor, DAYS
from app.routes.building_routes import get_working_hours

booking_bp = Blueprint('booking', __name__, url_prefix='/')

MOSCOW_TZ = ZoneInfo('Europe/Moscow')


def get_building(room_id):
    with get_db_cursor() as cur:
        cur.execute("SELECT building_id FROM rooms WHERE id = %s", (room_id,))
        return cur.fetchone()


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
        day_start = datetime.combine(current_date, datetime.min.time(), tzinfo=MOSCOW_TZ)
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

            opening_datetime = datetime.combine(current_date, open_time, tzinfo=MOSCOW_TZ)
            if close_time > open_time:
                closing_datetime = datetime.combine(current_date, close_time, tzinfo=MOSCOW_TZ)
            else:
                closing_datetime = datetime.combine(current_date + one_day, close_time, tzinfo=MOSCOW_TZ)

            if segment_start < opening_datetime or segment_end > closing_datetime:
                return False

        current_date += one_day

    return True



@booking_bp.route('/booking/<int:room_id>/new', methods=['GET', 'POST'])
def booking_request(room_id):
    building_id = get_building(room_id)

    if not building_id:
        flash('Комната не найдена.', 'error')
        return redirect(url_for('building.browse'))

    if request.method == 'POST':
        try:
            booking_start_str = request.form.get('booking_start')
            booking_time_str = request.form.get('booking_time')

            if not booking_start_str or not booking_time_str:
                flash('Пожалуйста, заполните все поля.', 'error')
                return redirect(request.url)

            booking_start = datetime.strptime(booking_start_str, '%Y-%m-%dT%H:%M')
            booking_time = int(booking_time_str)

            entry_time = booking_start.replace(tzinfo=MOSCOW_TZ)
            exit_time = entry_time + timedelta(minutes=booking_time)

            if not is_available(building_id, room_id, entry_time, exit_time):
                flash('Комната уже забронирована на выбранное время.', 'error')
                return redirect(request.url)

            user_id = session.get('user_id')

            with get_db_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO bookings (room_id, booking_user_id, entry_time, exit_time, is_automatic)
                    VALUES (%s, %s, %s, %s, %s)
                """, (room_id, user_id, entry_time, exit_time, False))  # TODO Автоматический приём

            flash('Заявка на бронирование успешно создана.', 'success')
            return redirect(url_for('building.browse'))

        except (ValueError, TypeError) as e:
            flash(f'Ошибка в формате данных: {e}', 'error')
            return redirect(request.url)
        except Exception as e:
            flash(f'Ошибка при сохранении бронирования: {e}', 'error')
            return redirect(request.url)

    return render_template('user/profile.html', room_id=room_id)
