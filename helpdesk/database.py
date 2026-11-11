
import sqlite3
import re
from pathlib import Path


# ==========================================
# DATABASE CONFIGURATION
# ==========================================

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = (
    BASE_DIR
    / "data"
    / "rail_capstone_pack"
    / "database"
    / "rail_timetable.db"
)


def get_connection():
    """Create a connection to the railway database."""

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}"
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    return conn


# ==========================================
# STATION NAME NORMALIZATION
# ==========================================

def normalize_name(name):
    """Normalize station names for comparison."""

    name = str(name).strip().lower()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name)

    return name


# Verified aliases based on the existing database records.
# Add more aliases only after verifying their station codes.

STATION_ALIASES = {
    "ernakulam": "ERS",
    "ernakulam junction": "ERS",
    "ernakulam jn": "ERS",

    "trivandrum": "TVC",
    "thiruvananthapuram": "TVC",
    "trivandrum central": "TVC",
    "thiruvananthapuram central": "TVC",

    "chengannur": "CNGR",

    "kottayam": "KTYM",
    "kollam": "QLN",
    "mavelikara": "MVLK",
    "kayankulam": "KYJ",
    "tiruvalla": "TRVL",
}


# ==========================================
# RESOLVE STATION NAME TO STATION CODE
# ==========================================

def resolve_station_code(keyword):
    """
    Resolve a station name or code to its database code.

    Resolution order:
    1. Exact station code
    2. Exact station name
    3. Verified station alias
    4. Partial station name
    """

    if not keyword or not str(keyword).strip():
        return {
            "error": "Station name or code cannot be empty."
        }

    keyword = str(keyword).strip()
    normalized = normalize_name(keyword)

    conn = get_connection()

    try:
        cursor = conn.cursor()

        # 1. Check exact station code.
        cursor.execute(
            """
            SELECT code, name, state
            FROM stations
            WHERE UPPER(code) = UPPER(?)
            """,
            (keyword,)
        )

        row = cursor.fetchone()

        if row:
            return dict(row)

        # 2. Check exact station name.
        cursor.execute(
            """
            SELECT code, name, state
            FROM stations
            """
        )

        stations = cursor.fetchall()

        for station in stations:
            if normalize_name(station["name"]) == normalized:
                return dict(station)

        # 3. Check verified aliases.
        alias_code = STATION_ALIASES.get(normalized)

        if alias_code:

            cursor.execute(
                """
                SELECT code, name, state
                FROM stations
                WHERE UPPER(code) = UPPER(?)
                """,
                (alias_code,)
            )

            row = cursor.fetchone()

            if row:
                return dict(row)

        # 4. Partial station name matching.
        matches = [
            dict(station)
            for station in stations
            if normalized in normalize_name(station["name"])
        ]

        if len(matches) == 1:
            return matches[0]

        if len(matches) > 1:
            return {
                "error": "Multiple stations matched.",
                "matches": matches
            }

        return {
            "error": f"Station '{keyword}' was not found."
        }

    finally:
        conn.close()


# ==========================================
# SEARCH STATIONS
# ==========================================

def search_stations(keyword):
    """Search stations by name, alias or station code."""

    if not keyword or not str(keyword).strip():
        return {
            "error": "Please provide a station name or code."
        }

    # First try exact and alias resolution.
    resolved = resolve_station_code(keyword)

    if "code" in resolved:
        return [
            (
                resolved["code"],
                resolved["name"],
                resolved["state"]
            )
        ]

    # Return ambiguous matches if available.
    if "matches" in resolved:
        return [
            (
                station["code"],
                station["name"],
                station["state"]
            )
            for station in resolved["matches"]
        ]

    # Otherwise perform a normal partial search.
    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT code, name, state
            FROM stations
            WHERE name LIKE ?
               OR code LIKE ?
            ORDER BY name
            LIMIT 20
            """,
            (
                f"%{keyword.strip()}%",
                f"%{keyword.strip()}%"
            )
        )

        return [
            tuple(row)
            for row in cursor.fetchall()
        ]

    finally:
        conn.close()


# ==========================================
# SEARCH TRAINS
# ==========================================

def search_trains(from_code, to_code):
    """
    Find direct trains between two stations.

    Accepts both station names and station codes.
    """

    origin = resolve_station_code(from_code)
    destination = resolve_station_code(to_code)

    if "error" in origin:
        return {
            "error": f"Origin station: {origin['error']}",
            "details": origin
        }

    if "error" in destination:
        return {
            "error": f"Destination station: {destination['error']}",
            "details": destination
        }

    origin_code = origin["code"]
    destination_code = destination["code"]

    if origin_code == destination_code:
        return {
            "error": "Origin and destination cannot be the same."
        }

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                number,
                name,
                departure,
                arrival,
                duration_min,
                distance_km
            FROM trains
            WHERE UPPER(from_station_code) = UPPER(?)
              AND UPPER(to_station_code) = UPPER(?)
            ORDER BY departure
            """,
            (origin_code, destination_code)
        )

        return [
            tuple(row)
            for row in cursor.fetchall()
        ]

    finally:
        conn.close()


# ==========================================
# GET TRAIN DETAILS
# ==========================================

def get_train_details(train_number):
    """Retrieve complete train information."""

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                t.number,
                t.name,
                t.type_code,
                t.zone,

                t.from_station_code,
                origin.name AS origin_name,

                t.to_station_code,
                destination.name AS destination_name,

                t.departure,
                t.arrival,
                t.duration_min,
                t.distance_km,
                t.return_train

            FROM trains t

            LEFT JOIN stations origin
                ON UPPER(t.from_station_code) = UPPER(origin.code)

            LEFT JOIN stations destination
                ON UPPER(t.to_station_code) = UPPER(destination.code)

            WHERE CAST(t.number AS TEXT) = ?
            """,
            (str(train_number).strip(),)
        )

        row = cursor.fetchone()

        if row is None:
            return {
                "error": f"Train {train_number} was not found."
            }

        return dict(row)

    finally:
        conn.close()


# ==========================================
# GET COMPLETE TRAIN ROUTE
# ==========================================

def get_train_route(train_number):
    """Retrieve all scheduled stops of a train."""

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                s.stop_sequence,
                st.code,
                st.name,
                s.arrival,
                s.departure,
                s.halt_min

            FROM schedules s

            JOIN stations st
                ON UPPER(s.station_code) = UPPER(st.code)

            WHERE CAST(s.train_number AS TEXT) = ?

            ORDER BY s.stop_sequence
            """,
            (str(train_number).strip(),)
        )

        return [
            tuple(row)
            for row in cursor.fetchall()
        ]

    finally:
        conn.close()
