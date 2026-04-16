from db import get_db_cursor


def create_tables():
    try:
        sql = """
-- Таблица зданий
CREATE TABLE IF NOT EXISTS buildings (
    id SERIAL PRIMARY KEY,
    city VARCHAR(255) NOT NULL,
    street VARCHAR(255) NOT NULL,
    description TEXT
);

-- Перечисление для дней недели
CREATE TYPE IF NOT EXISTS day_of_week_enum AS ENUM (
    'Monday',
    'Tuesday',
    'Wednesday',
    'Thursday',
    'Friday',
    'Saturday',
    'Sunday'
);

-- Таблица часов работы зданий
CREATE TABLE IF NOT EXISTS working_hours (
    building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
    day_of_week day_of_week_enum NOT NULL,
    open_time TIME NOT NULL,
    close_time TIME NOT NULL,
    is_closed BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (building_id, day_of_week)
);

-- Таблица помещений
CREATE TABLE IF NOT EXISTS rooms (
    id SERIAL PRIMARY KEY,
    building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
    is_available_for_booking BOOLEAN NOT NULL DEFAULT TRUE,
    auto_booking BOOLEAN NOT NULL DEFAULT FALSE,
    size NUMERIC(10,2),
    capacity INTEGER NOT NULL CHECK (capacity > 0)
);

CREATE INDEX IF NOT EXISTS idx_rooms_building_id ON rooms(building_id);

-- Справочник удобств
CREATE TABLE IF NOT EXISTS amenities (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL
);

-- Связь помещений и удобств
CREATE TABLE IF NOT EXISTS room_amenities (
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    amenity_id INTEGER NOT NULL REFERENCES amenities(id) ON DELETE CASCADE,
    PRIMARY KEY (room_id, amenity_id)
);

CREATE INDEX IF NOT EXISTS idx_room_amenities_room_id ON room_amenities(room_id);
CREATE INDEX IF NOT EXISTS idx_room_amenities_amenity_id ON room_amenities(amenity_id);

-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    login VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    phone VARCHAR(20) UNIQUE NOT NULL
);

-- Перечисления для прав
CREATE TYPE IF NOT EXISTS permission_enum AS ENUM (
    'VIEW',
    'CREATE_BUILDING',
    'MANAGE_BUILDING',
    'CREATE_ROOM',
    'MANAGE_ROOM',
    'REQUEST_BOOKING'
);

-- Таблица назначенных прав
CREATE TABLE IF NOT EXISTS user_permissions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    granter_id INTEGER REFERENCES users(id),
    permission permission_enum NOT NULL,
    building_id INTEGER REFERENCES buildings(id) ON DELETE CASCADE, -- NULL = глобальное право
    granting BOOLEAN NOT NULL DEFAULT FALSE,
    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE, -- NULL = на всё здание
    CONSTRAINT unique_user_permission_global UNIQUE NULLS NOT DISTINCT (user_id, permission, building_id, room_id)
);

CREATE INDEX IF NOT EXISTS idx_user_permissions_user_id ON user_permissions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_permissions_permission ON user_permissions(permission);
CREATE INDEX IF NOT EXISTS idx_user_permissions_building_id ON user_permissions(building_id);
CREATE INDEX IF NOT EXISTS idx_user_permissions_room_id ON user_permissions(room_id);

-- Таблица бронирований
CREATE TABLE IF NOT EXISTS bookings (
    id SERIAL PRIMARY KEY,
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    booking_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    manager_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    is_accepted BOOLEAN,
    is_automatic BOOLEAN NOT NULL DEFAULT FALSE,
    entry_time TIMESTAMP WITH TIME ZONE NOT NULL,
    exit_time TIMESTAMP WITH TIME ZONE NOT NULL,
    CHECK (entry_time < exit_time)
);
CREATE INDEX IF NOT EXISTS idx_bookings_room_id ON bookings(room_id);
CREATE INDEX IF NOT EXISTS idx_bookings_booking_user_id ON bookings(booking_user_id);
CREATE INDEX IF NOT EXISTS idx_bookings_manager_user_id ON bookings(manager_user_id);
CREATE INDEX IF NOT EXISTS idx_bookings_entry_exit ON bookings(entry_time, exit_time);
        """
        with get_db_cursor(commit=True) as cur:
            cur.execute(sql)
        print("Tables created successfully.")
    except Exception as e:
        print(f"Error creating tables: {e}")


if __name__ == '__main__':
    create_tables()
