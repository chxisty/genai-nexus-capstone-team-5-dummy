"""Build or refresh RailAssist's local document search index."""

from helpdesk.pipeline import build_index


def main() -> int:
    count, warnings = build_index(force=True)
    print(f"Indexed {count} page-aware document chunks.")
    if warnings:
        print("Some pages need OCR before they can be searched:")
        for warning in warnings:
            print(f"- {warning}")
        print("Install Tesseract with the relevant language packs and a PDF renderer, then rerun this command.")
    else:
        print("All supplied document pages produced searchable text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
