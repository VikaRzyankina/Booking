from db import get_db_cursor

VIEW = 'VIEW'
CREATE_BUILDING = 'CREATE_BUILDING'
MANAGE_BUILDING = 'MANAGE_BUILDING'
CREATE_ROOM = 'CREATE_ROOM'
MANAGE_ROOM = 'MANAGE_ROOM'
REQUEST_BOOKING = 'REQUEST_BOOKING'

ALL_PERMISSIONS = [
    VIEW, CREATE_BUILDING, MANAGE_BUILDING, CREATE_ROOM, MANAGE_ROOM, REQUEST_BOOKING
]


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
                     building_id: int = None, room_id: int = None) -> bool:
    with get_db_cursor(commit=True) as cur:
        if building_id is None:
            cover_condition = "up.building_id IS NULL"
            params_cover = (granter_id, permission)
        else:
            if room_id is None:
                cover_condition = "(up.building_id IS NULL OR up.building_id = %s)"
                params_cover = (granter_id, permission, building_id)
            else:
                cover_condition = """
                    (up.building_id IS NULL) OR
                    (up.building_id = %s AND (up.room_id IS NULL OR up.room_id = %s))
                """
                params_cover = (granter_id, permission, building_id, room_id)

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
        if not cur.fetchone()[0]:
            return False

        cur.execute("SELECT 1 FROM users WHERE id = %s", (user_id,))
        if not cur.fetchone():
            return False

        try:
            cur.execute("""
                INSERT INTO user_permissions
                    (user_id, granter_id, permission, building_id, room_id, granting)
                VALUES (%s, %s, %s, %s, %s, FALSE)
            """, (user_id, granter_id, permission, building_id, room_id))
            return True
        except Exception:
            return False
