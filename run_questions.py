"""Run a JSON question set and write RailAssist evaluation results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from helpdesk.pipeline import ask, reset_conversation


def _read_questions(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Question input must be a JSON list.")
    for index, item in enumerate(payload):
        if not isinstance(item, dict) or not isinstance(item.get("question"), str):
            raise ValueError(f"Question item {index + 1} must contain a text 'question'.")
    return payload


def run(questions_path: Path, results_path: Path) -> int:
    questions = _read_questions(questions_path)
    results: list[dict[str, Any]] = []
    for item in questions:
        reset_conversation()
        result = ask(item["question"])
        results.append({
            "id": item.get("id"),
            "question": item["question"],
            **result,
        })

    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(results)} answers to {results_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate RailAssist on a JSON question set")
    parser.add_argument("questions", type=Path, help="JSON list with id and question fields")
    parser.add_argument("results", type=Path, help="Destination JSON file")
    args = parser.parse_args()
    try:
        return run(args.questions, args.results)
    except Exception as exc:
        parser.exit(1, f"RailAssist evaluation failed ({type(exc).__name__}): {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
