# Indian Railways help desk: capstone data pack (version B)

Build a passenger help desk assistant for Indian Railways. Your team writes one function, `ask(question)`, that:

- answers rule questions (refunds, cancellation, Tatkal, booking limits, charts) from the documents, with the document name and page;
- answers timetable questions from the SQLite database, using read-only text-to-SQL;
- says "I don't know" when the answer is not in the pack, or when the request is unsafe.

**This is an unofficial learning project.** It is built on public documents from Indian Railways, IRCTC and PIB, and on a CC0 timetable snapshot from 2016. It is not an official railway service. Rules change often: the answers we expect follow the documents in this pack, which may not be the latest rules on the day you read this.

## What's in the pack

```
README.md                                            this file
SOURCES.md                                           where each document and the timetable came from
documents/indianrail_refund_rules_2015.html          refund rules from 12.11.2015: table of old vs revised charges
documents/irctc_refund_rules_jan2026.pdf             IRCTC refund and TDR rules (updated Jan 2026), 11 pages
documents/rb_cc10_2024_advance_reservation.pdf       Railway Board circular 10/2024: booking limit 120 to 60 days (scanned)
documents/rb_cc08_2025_tatkal.pdf                    Railway Board circular 08/2025: Aadhaar for Tatkal (Hindi pages scanned)
documents/rb_cc10_2025_reservation_charts.pdf        Railway Board circular 10/2025: when first charts are made (scanned)
documents/rb_cc08_2026_vande_bharat_sleeper_refund.pdf  circular 08/2026 + gazette G.S.R. 41(E): Vande Bharat Sleeper refunds
documents/pib_2026-03-24_reform_express.html         PIB press release of 24 Mar 2026: new cancellation windows and more
database/rail_timetable.db                           SQLite timetable (2016 snapshot): stations, trains, schedules
database/schema.md                                   every table and column, and the data's quirks
questions/sample_questions.json                      10 practice questions with model answers and sources
```

## The database in one minute

| Table | Rows | What it holds |
|---|---|---|
| `stations` | 8,990 | code, name, state, zone, location |
| `train_types` | 16 | what type codes like `Raj` or `Shtb` mean |
| `trains` | 5,208 | number, name, type, start and end station, times, distance, classes |
| `schedules` | 417,080 | every station on every route, in order, with day, arrival, departure, `is_halt` |
| `stops` (view) | 104,151 | only the rows where the train really stops (`is_halt = 1`) |

Read `database/schema.md` before writing prompts for text-to-SQL. Two things trip people up: `schedules` includes stations a train only passes through (use `stops`), and overnight journeys need the `day` column.

## Things to watch in the documents

- Two PDFs are scanned images with no text layer, and the Tatkal circular has scanned Hindi pages. You need OCR for some answers.
- Some documents disagree because the rules changed over time. When they do, the newer document wins: check the dates.
- Rules for specific trains (for example Vande Bharat Sleeper) override the general rules for those trains.
- Two documents are HTML, so they have no page numbers: cite them with `"page": null`.

## What your system returns

Every question goes through one function, `ask(question)`, which returns:

```json
{"answer": "the reply, in plain words", "sources": [{"doc": "irctc_refund_rules_jan2026.pdf", "page": 3}], "sql": null, "dont_know": false}
```

- `sources`: the documents used, by file name, with the page. The page is `null` for the HTML documents.
- `sql`: the query it ran, when it used the database; otherwise `null`.
- `dont_know`: `true` when it declines (not in the pack, out of scope, or unsafe).

## Sample questions

Each question in `questions/sample_questions.json` has `id`, `question`, the model `answer`, its `sources` (document and page), and, for timetable questions, the `sql` that finds the answer. The hidden test set has 30 questions of the same kinds, and it stays hidden: after the deadline we run `python run_questions.py <questions> <results>` from your repo, with a question file that has only `id` and `question`. The results file is a list with one object per question: the `id` and `question`, plus everything `ask()` returned:

```json
{"id": "H01", "question": "...", "answer": "...", "sources": [{"doc": "rb_cc10_2024_advance_reservation.pdf", "page": 1}], "sql": null, "dont_know": false}
```

## How to start

1. Open the database (`sqlite3 database/rail_timetable.db`, or Python's `sqlite3`) and run a few queries from `schema.md`.
2. Parse the documents page by page, keep the file name and page number with every chunk, and check which pages come out empty: those need OCR.
3. Get a simple version answering all 10 sample questions end to end first, and check it against the model answers. Then improve one part at a time, and keep a change only when the numbers go up.
4. Run all SQL on a read-only connection: `sqlite3.connect("file:database/rail_timetable.db?mode=ro", uri=True)`.

The class notebooks and your assignments are a starting point, not a limit: use any free library or model that makes the answers more accurate.
