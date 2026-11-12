"""Guarded, read-only SQL access for natural-language timetable questions."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from helpdesk.documents import PROJECT_ROOT


DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "rail_capstone_pack" / "database" / "rail_timetable.db"
MAX_RESULT_ROWS = 50
MAX_SQL_LENGTH = 12_000
_READ_PREFIX = re.compile(r"^(?:SELECT|WITH)\b", re.IGNORECASE)


class ReadOnlyQueryError(ValueError):
    """Raised when SQL is invalid or attempts to change database state."""


def _authorizer(action: int, arg1: str | None, arg2: str | None, database: str | None, source: str | None) -> int:
    del arg1, arg2, database, source
    allowed = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
    }
    recursive = getattr(sqlite3, "SQLITE_RECURSIVE", None)
    if recursive is not None:
        allowed.add(recursive)
    return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY


def run_readonly_query(sql: str, db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Run exactly one SELECT/WITH query with a hard row and execution limit."""
    if not isinstance(sql, str) or not sql.strip():
        raise ReadOnlyQueryError("Provide one read-only SELECT query.")
    if len(sql) > MAX_SQL_LENGTH:
        raise ReadOnlyQueryError("The SQL query is too long.")

    query = sql.strip()
    if query.endswith(";"):
        query = query[:-1].rstrip()
    if not _READ_PREFIX.match(query):
        raise ReadOnlyQueryError("Only SELECT or WITH queries are allowed.")

    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Timetable database not found: {path}")

    uri = f"{path.as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.set_authorizer(_authorizer)
        connection.set_progress_handler(lambda: 1, 1_000_000)

        # Wrapping caps rows even if the model omits LIMIT or asks for a huge one.
        bounded_query = f"SELECT * FROM ({query}) AS railassist_limited_result LIMIT {MAX_RESULT_ROWS + 1}"
        try:
            cursor = connection.execute(bounded_query)
            rows = cursor.fetchmany(MAX_RESULT_ROWS + 1)
        except sqlite3.Error as exc:
            message = str(exc)
            if "not authorized" in message.lower():
                raise ReadOnlyQueryError("The query attempted a disallowed database operation.") from exc
            if "interrupted" in message.lower():
                raise ReadOnlyQueryError("The query exceeded the database work limit.") from exc
            raise ReadOnlyQueryError(f"The query could not be run: {message}") from exc

        truncated = len(rows) > MAX_RESULT_ROWS
        rows = rows[:MAX_RESULT_ROWS]
        return {
            "columns": [column[0] for column in cursor.description or []],
            "rows": [{key: row[key] for key in row.keys()} for row in rows],
            "truncated": truncated,
        }
    finally:
        connection.close()
