from functools import wraps

from db import get_db_cursor
from flask import session, flash, redirect, url_for, abort

VIEW = 'VIEW'
CREATE_BUILDING = 'CREATE_BUILDING'
MANAGE_BUILDING = 'MANAGE_BUILDING'
CREATE_ROOM = 'CREATE_ROOM'
MANAGE_ROOM = 'MANAGE_ROOM'
MANAGE_BOOKING_REQUESTS = 'MANAGE_BOOKING_REQUESTS'
REQUEST_BOOKING = 'REQUEST_BOOKING'

ALL_PERMISSIONS = [
    VIEW, CREATE_BUILDING, MANAGE_BUILDING, CREATE_ROOM, MANAGE_ROOM, MANAGE_BOOKING_REQUESTS, REQUEST_BOOKING
]

PERMISSION_HIERARCHY = [CREATE_BUILDING, MANAGE_BUILDING, CREATE_ROOM, MANAGE_ROOM, MANAGE_BOOKING_REQUESTS]


def _higher_permissions(permission: str) -> list:
    if permission not in PERMISSION_HIERARCHY:
        return []
    idx = PERMISSION_HIERARCHY.index(permission)
    return PERMISSION_HIERARCHY[:idx]


PERMISSION_LABELS = {
    VIEW: 'Просмотр',
    CREATE_BUILDING: 'Создание зданий',
    MANAGE_BUILDING: 'Управление зданием',
    CREATE_ROOM: 'Создание комнат',
    MANAGE_ROOM: 'Управление комнатой',
    MANAGE_BOOKING_REQUESTS: 'Управление бронированиями',
    REQUEST_BOOKING: 'Бронирование',
}


def check_permission(user_id: int, permission: str, building_id: int = None, room_id: int = None) -> bool:
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT 1
                FROM user_permissions up
                WHERE up.user_id = %s
                  AND up.permission = %s
                  AND (up.building_id IS NULL OR up.building_id = %s)
                  AND (up.room_id IS NULL OR up.room_id = %s)
            )
        """, (user_id, permission, building_id, room_id))
        return cur.fetchone()[0]


def grant_permission(granter_id: int, user_id: int, permission: str,
                     building_id: int = None, room_id: int = None,
                     with_granting: bool = False) -> bool:
    with get_db_cursor(commit=True) as cur:
        if building_id is None:
            cover_condition = "up.building_id IS NULL"
            params_cover = (granter_id, permission)
            hier_cover_condition = "up.building_id IS NULL"
        else:
            if room_id is None:
                cover_condition = "(up.building_id IS NULL OR up.building_id = %s)"
                params_cover = (granter_id, permission, building_id)
                hier_cover_condition = "(up.building_id IS NULL OR up.building_id = %s)"
            else:
                cover_condition = """
                    (up.building_id IS NULL) OR
                    (up.building_id = %s AND (up.room_id IS NULL OR up.room_id = %s))
                """
                params_cover = (granter_id, permission, building_id, room_id)
                hier_cover_condition = """
                    (up.building_id IS NULL) OR
                    (up.building_id = %s AND (up.room_id IS NULL OR up.room_id = %s))
                """

        query_cover = f"""
            SELECT EXISTS (
                SELECT 1
                FROM user_permissions up
                WHERE up.user_id = %s
                  AND up.permission = %s
                  AND up.granting = TRUE
                  AND ({cover_condition})
            )
        """
        cur.execute(query_cover, params_cover)
        has_authority = cur.fetchone()[0]

        if not has_authority:
            higher = _higher_permissions(permission)
            if higher:
                placeholders = ','.join(['%s'] * len(higher))
                if building_id is None:
                    hier_params = (granter_id, *higher)
                elif room_id is None:
                    hier_params = (granter_id, *higher, building_id)
                else:
                    hier_params = (granter_id, *higher, building_id, room_id)

                cur.execute(f"""
                    SELECT EXISTS (
                        SELECT 1 FROM user_permissions up
                        WHERE up.user_id = %s
                          AND up.permission IN ({placeholders})
                          AND ({hier_cover_condition})
                    )
                """, hier_params)
                has_authority = cur.fetchone()[0]

        if not has_authority:
            return False

        cur.execute("SELECT 1 FROM users WHERE id = %s", (user_id,))
        if not cur.fetchone():
            return False

        try:
            cur.execute("""
                INSERT INTO user_permissions
                    (user_id, granter_id, permission, building_id, room_id, granting)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_id, granter_id, permission, building_id, room_id, with_granting))
            return True
        except Exception:
            return False


def revoke_permission(revoker_id: int, user_id: int, permission: str,
                      building_id: int = None, room_id: int = None) -> bool:
    if not check_granting(revoker_id, permission, building_id=building_id, room_id=room_id):
        return False
    with get_db_cursor(commit=True) as cur:
        cur.execute("""
            DELETE FROM user_permissions
            WHERE user_id = %s AND permission = %s
              AND building_id IS NOT DISTINCT FROM %s
              AND room_id IS NOT DISTINCT FROM %s
        """, (user_id, permission, building_id, room_id))
        return cur.rowcount > 0


def check_granting(user_id: int, permission: str, building_id: int = None, room_id: int = None) -> bool:
    with get_db_cursor() as cur:
        if building_id is None:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM user_permissions
                    WHERE user_id = %s AND permission = %s
                      AND granting = TRUE AND building_id IS NULL
                )
            """, (user_id, permission))
        elif room_id is None:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM user_permissions
                    WHERE user_id = %s AND permission = %s
                      AND granting = TRUE
                      AND (building_id IS NULL OR building_id = %s)
                )
            """, (user_id, permission, building_id))
        else:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM user_permissions
                    WHERE user_id = %s AND permission = %s
                      AND granting = TRUE
                      AND (
                          building_id IS NULL OR
                          (building_id = %s AND (room_id IS NULL OR room_id = %s))
                      )
                )
            """, (user_id, permission, building_id, room_id))

        if cur.fetchone()[0]:
            return True

        higher = _higher_permissions(permission)
        if not higher:
            return False

        placeholders = ','.join(['%s'] * len(higher))
        if building_id is None:
            cur.execute(f"""
                SELECT EXISTS (
                    SELECT 1 FROM user_permissions
                    WHERE user_id = %s AND permission IN ({placeholders})
                      AND building_id IS NULL
                )
            """, (user_id, *higher))
        elif room_id is None:
            cur.execute(f"""
                SELECT EXISTS (
                    SELECT 1 FROM user_permissions
                    WHERE user_id = %s AND permission IN ({placeholders})
                      AND (building_id IS NULL OR building_id = %s)
                )
            """, (user_id, *higher, building_id))
        else:
            cur.execute(f"""
                SELECT EXISTS (
                    SELECT 1 FROM user_permissions
                    WHERE user_id = %s AND permission IN ({placeholders})
                      AND (
                          building_id IS NULL OR
                          (building_id = %s AND (room_id IS NULL OR room_id = %s))
                      )
                )
            """, (user_id, *higher, building_id, room_id))

        return cur.fetchone()[0]


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            flash('Необходима авторизация.', 'error')
            return redirect(url_for('user.login'))
        return f(*args, **kwargs)
    return wrapper


def require_permission(permission, building_id_arg=None, room_id_arg=None):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            logged_in_id = session.get('user_id')
            user_id = logged_in_id or 2
            building_id = kwargs.get(building_id_arg) if building_id_arg else None
            room_id = kwargs.get(room_id_arg) if room_id_arg else None
            if not check_permission(user_id, permission, building_id, room_id):
                if not logged_in_id:
                    flash('Необходима авторизация.', 'error')
                    return redirect(url_for('user.login'))
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator
