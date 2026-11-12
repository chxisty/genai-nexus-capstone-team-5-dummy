"""Question routing, source-grounded answering, and terminal-session memory."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq

from helpdesk.documents import DEFAULT_DATA_DIR, DEFAULT_INDEX_PATH, DocumentChunk, load_or_build_chunks
from helpdesk.search import BM25Search, SearchHit
from helpdesk.sql import DEFAULT_DB_PATH, run_readonly_query


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_TOOL_CALLS = 6
_client: Groq | None = None
_search: BM25Search | None = None
_chunks: list[DocumentChunk] = []
_index_warnings: list[str] = []
_conversation: list[dict[str, str]] = []


_SYSTEM_PROMPT = """You are RailAssist, a careful terminal helpdesk for Indian Railways.

GROUNDING
- Answer railway policy questions only from DOCUMENT EVIDENCE supplied in this turn.
- Answer timetable questions only from the read-only timetable tools supplied in this turn.
- Do not use outside knowledge, guess, or invent a fare, train, time, station, rule, or source.
- The database is a static 2016 timetable. Never present it as live status, seat availability,
  PNR state, or current operations. State when the old snapshot may not reflect today's service.
- If the supplied evidence cannot answer the question, say you don't know and set dont_know=true.
- Where documents conflict, prefer the newer dated rule and explain the applicable source.
- Cite only document names and page numbers present in DOCUMENT EVIDENCE. HTML pages use null.
- For every timetable question, call run_timetable_query. Use one SELECT/WITH statement and the `stops` view for actual halts and station-to-station journeys.

OUTPUT
Return one JSON object only, with exactly these fields:
{"answer":"plain-language answer","sources":[{"doc":"file name","page":1}],"sql":null,"dont_know":false}
Use sql=null for document-only or declined responses. When a SQL tool was run, the application
will attach that exact query. Do not put Markdown fences around the JSON.
"""


_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_timetable_query",
            "description": "Run one read-only SQL query against the 2016 timetable. Use this for every timetable fact. Only SELECT/WITH is allowed; results are capped at 50 rows.",
            "parameters": {"type": "object", "properties": {"sql": {"type": "string", "description": "One SELECT or WITH query using the documented SQLite schema."}}, "required": ["sql"]},
        },
    },
]


def _get_client() -> Groq:
    global _client
    if _client is not None:
        return _client

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key or api_key.lower() in {"your_groq_api_key_here", "placeholder", "replace_me"}:
        raise RuntimeError("GROQ_API_KEY is not configured. Put your key in the local .env file.")
    _client = Groq(
        api_key=api_key,
        timeout=float(os.getenv("GROQ_TIMEOUT_SECONDS", "30")),
        max_retries=2,
    )
    return _client


def _get_search() -> tuple[BM25Search, list[str]]:
    global _search, _chunks, _index_warnings
    if _search is None:
        _chunks, _index_warnings = load_or_build_chunks(DEFAULT_DATA_DIR, DEFAULT_INDEX_PATH)
        _search = BM25Search(_chunks)
    return _search, _index_warnings


def reset_conversation() -> None:
    """Clear in-memory follow-up context for this process."""
    _conversation.clear()


def index_warnings() -> list[str]:
    """Return extraction warnings after loading the document collection."""
    _get_search()
    return list(_index_warnings)


def _evidence_text(hits: list[SearchHit]) -> str:
    if not hits:
        return "No relevant document passages were found."
    blocks = []
    for number, hit in enumerate(hits, start=1):
        page = "HTML (no page number)" if hit.chunk.page is None else f"page {hit.chunk.page}"
        date = f", issued {hit.chunk.date}" if hit.chunk.date else ""
        blocks.append(
            f"[{number}] {hit.chunk.doc}, {page}{date}\n{hit.chunk.text}"
        )
    return "\n\n".join(blocks)


def _execute_tool(name: str, arguments: dict[str, Any]) -> tuple[Any, str | None]:
    if name == "run_timetable_query":
        sql = arguments["sql"]
        return run_readonly_query(sql, DEFAULT_DB_PATH), sql
    raise ValueError(f"Unknown timetable tool: {name}")


def _decode_response(content: str | None) -> dict[str, Any]:
    if not content:
        return {}
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE)
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for position, char in enumerate(stripped):
            if char == "{":
                try:
                    value, _ = decoder.raw_decode(stripped[position:])
                    return value if isinstance(value, dict) else {}
                except json.JSONDecodeError:
                    continue
    return {"answer": content}


def _source_key(source: dict[str, Any]) -> tuple[str, int | None] | None:
    doc = source.get("doc")
    page = source.get("page")
    if not isinstance(doc, str):
        return None
    if page is not None and not isinstance(page, int):
        return None
    return doc, page


def _format_result(
    raw_content: str | None,
    hits: list[SearchHit],
    sql_used: str | None,
    database_was_used: bool,
) -> dict[str, Any]:
    parsed = _decode_response(raw_content)
    answer = parsed.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        answer = "I don't know based on the railway documents and timetable available here."

    allowed_sources = {
        (hit.chunk.doc, hit.chunk.page)
        for hit in hits
    }
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None]] = set()
    proposed = parsed.get("sources", [])
    if isinstance(proposed, list):
        for item in proposed:
            if isinstance(item, dict):
                key = _source_key(item)
                if key in allowed_sources and key not in seen:
                    sources.append({"doc": key[0], "page": key[1]})
                    seen.add(key)

    dont_know = bool(parsed.get("dont_know", False))
    if not dont_know and hits and not database_was_used and not sources:
        # Never return an uncited policy answer when evidence was supplied.
        for hit in hits[:3]:
            key = (hit.chunk.doc, hit.chunk.page)
            if key not in seen:
                sources.append({"doc": key[0], "page": key[1]})
                seen.add(key)
    if not hits and not database_was_used:
        dont_know = True
        if "don't know" not in answer.lower() and "do not know" not in answer.lower():
            answer = "I don't know based on the railway documents and timetable available here."

    return {
        "answer": answer.strip(),
        "sources": sources,
        "sql": sql_used,
        "dont_know": dont_know,
    }


def ask(question: str) -> dict[str, Any]:
    """Answer a railway question with document citations and/or safe SQL evidence."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Enter a railway question.")
    normalized = re.sub(r"\s+", " ", question).strip()
    if len(normalized) > 1500:
        raise ValueError("Question is too long; keep it under 1,500 characters.")

    search, _ = _get_search()
    hits = search.search(normalized, limit=6)
    evidence = _evidence_text(hits)
    system = (
        _SYSTEM_PROMPT
        + "\n\nTIMETABLE SCHEMA\n"
        + "stations(code, name, state, zone, address, latitude, longitude); "
        + "trains(number, name, type_code, zone, from_station_code, to_station_code, departure, arrival, duration_min, distance_km, return_train, has_1a, has_2a, has_3a, has_sl, has_cc, has_fc); "
        + "schedules(train_number, stop_sequence, station_code, day, arrival, departure, halt_min, is_halt); "
        + "stops is the view of schedules where is_halt=1. Join stops by train_number and require increasing stop_sequence for journeys between two intermediate stations. Resolve station names with SELECT code, name FROM stations WHERE name LIKE '%keyword%'.\n\n"
        + "DOCUMENT EVIDENCE\n"
        + evidence
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    messages.extend(_conversation[-12:])
    messages.append({"role": "user", "content": normalized})
    sql_used: str | None = None
    database_was_used = False
    client = _get_client()

    for _ in range(MAX_TOOL_CALLS):
        try:
            response = client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
                messages=messages,
                tools=_TOOLS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=int(os.getenv("GROQ_MAX_TOKENS", "2048")),
            )
        except Exception as exc:
            # SDK exceptions can contain request headers. Do not surface them verbatim.
            raise RuntimeError(f"Groq request failed ({type(exc).__name__}). Check connectivity and model configuration.") from None

        assistant_message = response.choices[0].message
        calls = assistant_message.tool_calls or []
        if not calls:
            result = _format_result(assistant_message.content, hits, sql_used, database_was_used)
            _conversation.extend([
                {"role": "user", "content": normalized},
                {"role": "assistant", "content": result["answer"]},
            ])
            del _conversation[:-20]
            return result

        messages.append(assistant_message.model_dump(exclude_none=True))
        for call in calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
                value, executed_sql = _execute_tool(call.function.name, arguments)
                database_was_used = True
                if call.function.name == "run_timetable_query":
                    sql_used = executed_sql
            except Exception as exc:
                value = {"error": str(exc)}
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(value, ensure_ascii=False, default=str),
            })

    return {
        "answer": "I could not finish the request within the tool-call limit.",
        "sources": [],
        "sql": sql_used,
        "dont_know": True,
    }


def build_index(force: bool = False) -> tuple[int, list[str]]:
    """Build or refresh the local document index and return count plus warnings."""
    global _search, _chunks, _index_warnings
    _chunks, _index_warnings = load_or_build_chunks(DEFAULT_DATA_DIR, DEFAULT_INDEX_PATH, force=force)
    _search = BM25Search(_chunks)
    return len(_chunks), list(_index_warnings)
