from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app.db import get_db_cursor

booking_bp = Blueprint('booking', __name__, url_prefix='/')


def get_building(room_id):
    with get_db_cursor() as cur:
        cur.execute("SELECT building_id FROM rooms WHERE id = %s", (room_id,))
        return cur.fetchone()


def is_available(building_id, room_id, entry_time, exit_time):
    # TODO
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

            tz = ZoneInfo('UTC')
            entry_time = booking_start.replace(tzinfo=tz)
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
