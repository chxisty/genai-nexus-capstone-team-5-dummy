import sqlite3

import pytest

from helpdesk.sql import ReadOnlyQueryError, run_readonly_query


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "timetable.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE trains (number TEXT, name TEXT)")
    connection.execute("INSERT INTO trains VALUES ('16303', 'Vanchinad Express')")
    connection.commit()
    connection.close()
    return path


def test_readonly_query_returns_columns_and_rows(database):
    result = run_readonly_query("SELECT number, name FROM trains", database)

    assert result["columns"] == ["number", "name"]
    assert result["rows"] == [{"number": "16303", "name": "Vanchinad Express"}]
    assert result["truncated"] is False


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM trains",
        "UPDATE trains SET name = 'Changed'",
        "PRAGMA table_info(trains)",
        "SELECT * FROM trains; DROP TABLE trains",
    ],
)
def test_mutating_or_multi_statement_sql_is_rejected(database, sql):
    with pytest.raises(ReadOnlyQueryError):
        run_readonly_query(sql, database)


def test_result_rows_are_capped(database):
    connection = sqlite3.connect(database)
    connection.executemany("INSERT INTO trains VALUES (?, ?)", [(str(i), "Train") for i in range(80)])
    connection.commit()
    connection.close()

    result = run_readonly_query("SELECT number FROM trains", database)

    assert len(result["rows"]) == 50
    assert result["truncated"] is True
