
import pytest

from helpdesk.database import (
    search_stations,
    search_trains,
    get_train_details,
    get_train_route,
)


# ==========================================
# STATION SEARCH TESTS
# ==========================================

def test_search_station_by_code():
    result = search_stations("ERS")

    assert len(result) > 0
    assert result[0][0] == "ERS"


def test_search_station_by_name():
    result = search_stations("Ernakulam")

    assert len(result) > 0
    assert result[0][0] == "ERS"


def test_search_invalid_station():
    result = search_stations("InvalidStationXYZ")

    assert result == []


# ==========================================
# TRAIN SEARCH TESTS
# ==========================================

def test_search_trains_ers_to_tvc():
    result = search_trains("ERS", "TVC")

    assert len(result) > 0
    assert result[0][0] == "16303"


def test_search_trains_same_station():
    result = search_trains("ERS", "ERS")

    assert "error" in result


def test_search_trains_invalid_station():
    result = search_trains(
        "InvalidStationXYZ",
        "TVC"
    )

    assert "error" in result


# ==========================================
# TRAIN DETAILS TESTS
# ==========================================

def test_get_train_details():
    result = get_train_details("16303")

    assert result["number"] == "16303"
    assert result["name"] == "Vanchinad Express"
    assert result["from_station_code"] == "ERS"
    assert result["to_station_code"] == "TVC"
    assert result["duration_min"] == 280
    assert result["distance_km"] == 220


def test_get_invalid_train_details():
    result = get_train_details("99999")

    assert "error" in result


# ==========================================
# TRAIN ROUTE TESTS
# ==========================================

def test_get_train_route():
    result = get_train_route("16303")

    assert len(result) == 42
    assert result[0][1] == "ERS"
    assert result[-1][1] == "TVC"


def test_train_route_contains_chengannur():
    result = get_train_route("16303")

    station_codes = [
        stop[1] for stop in result
    ]

    assert "CNGR" in station_codes


def test_get_invalid_train_route():
    result = get_train_route("99999")

    assert result == []
