# RailAssist AI

RailAssist is a Python terminal helpdesk for Indian Railways. It uses Groq tool calling for question routing, a local SQLite timetable for train facts, and page-aware retrieval from the supplied railway documents. It is an unofficial learning project and does not provide live train status, PNR status, seat availability, or fares.

## Requirements

- Python 3.10 or newer.
- The supplied `data/rail_capstone_pack/` directory.
- A Groq API key stored only in a local `.env` file.
- Optional: Tesseract OCR plus `pdftoppm` or `pdftocairo` for OCR on all platforms. On Windows, the built-in English OCR engine is used automatically when available.

The timetable is a 2016 snapshot. Treat its schedules as historical scheduled data, not current service information. See `data/rail_capstone_pack/SOURCES.md` and `data/rail_capstone_pack/database/schema.md` for provenance and limitations.

## Install

From the project directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` locally and set `GROQ_API_KEY` to your own key. Never put a real key in `.env.example`, source files, or Git. If a key has been exposed, revoke it with Groq before replacing it.

## Ask from the terminal

Ask one question:

```powershell
python ask.py "What is the station code for Chengannur?"
python ask.py "Find trains from Ernakulam to Trivandrum"
python ask.py "What are the cancellation rules for a 3AC ticket?"
```

Start an interactive session with follow-up memory:

```powershell
python ask.py
```

Type `reset` to clear the current conversation or `exit` to quit. Answers show their document/page citations and the SQL query when a raw timetable query was used. The first run builds a local document index automatically; later runs reuse it and refresh it when source documents change.

To explicitly rebuild the document index:

```powershell
python build_index.py
```

The index is generated locally under `index/` and is ignored by Git. Install Tesseract and a PDF renderer if the command reports image-only pages that could not be read. The Windows OCR fallback uses installed Windows recognition languages (often English only); Tesseract can use additional language packs configured with `RAILASSIST_OCR_LANG`.

## Evaluate a question set

Input is a JSON list whose items contain `id` and `question` fields. Additional reference fields are ignored.

```powershell
python run_questions.py data/rail_capstone_pack/questions/sample_questions.json results.json
```

Each output item contains `id`, `question`, `answer`, `sources`, `sql`, and `dont_know`.

## How it works

1. HTML and PDF files are extracted into chunks that retain the document name and page.
2. BM25 lexical retrieval ranks passages, with extra weight for exact codes and numbers.
3. Groq can call station/train helpers or request a read-only SQLite `SELECT`/`WITH` query. SQL execution is capped at 50 rows and protected with SQLite read-only mode and an authorizer.
4. The final answer is constrained to the retrieved passages and database results. The model returns an `I don't know` response when the supplied sources do not support an answer.

Document retrieval does not use outside web content. Image-only scanned pages require OCR for complete coverage. Tests use mocks and local SQLite fixtures; they do not call Groq.

## Tests

```powershell
python -m pytest tests
```
