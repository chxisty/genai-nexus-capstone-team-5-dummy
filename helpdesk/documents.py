"""Read railway source documents into page-aware, searchable chunks."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from pypdf import PdfReader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "rail_capstone_pack"
DEFAULT_INDEX_PATH = PROJECT_ROOT / "index" / "railassist_index.json"
INDEX_VERSION = 1
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 160

DOCUMENT_DATES = {
    "irctc_refund_rules_jan2026.pdf": "2026-01-19",
    "rb_cc10_2024_advance_reservation.pdf": "2024-10-16",
    "rb_cc08_2025_tatkal.pdf": "2025-06-10",
    "rb_cc10_2025_reservation_charts.pdf": "2025-07-02",
    "rb_cc08_2026_vande_bharat_sleeper_refund.pdf": "2026-01-19",
    "pib_2026-03-24_reform_express.html": "2026-03-24",
    "indianrail_refund_rules_2015.html": "2015-11-12",
}

HINDI_ONLY_PAGES = {
    "rb_cc10_2024_advance_reservation.pdf": {2},
    "rb_cc08_2025_tatkal.pdf": {3, 4, 5, 6},
    "rb_cc10_2025_reservation_charts.pdf": {1},
    "rb_cc08_2026_vande_bharat_sleeper_refund.pdf": {3, 4},
}


@dataclass(frozen=True)
class DocumentChunk:
    """A text segment tied to its source document and page."""

    doc: str
    page: int | None
    date: str | None
    text: str
    chunk: int


class _VisibleTextParser(HTMLParser):
    """Extract readable HTML text while dropping scripts and styling."""

    _SKIP = {"script", "style", "noscript", "svg"}
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP:
            self.skip_depth += 1
        elif not self.skip_depth and tag in self._BLOCK:
            self.parts.append("\n")
        elif not self.skip_depth and tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in self._BLOCK:
            self.parts.append("\n")
        elif not self.skip_depth and tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def _clean_text(value: str) -> str:
    value = html.unescape(value).replace("\x00", " ")
    value = re.sub(r"[ \t\xa0]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _read_html(path: Path) -> list[tuple[int | None, str]]:
    parser = _VisibleTextParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    parser.close()
    text = _clean_text("".join(parser.parts))
    return [(None, text)] if text else []


def _ocr_page(pdf_path: Path, page_number: int, renderer: str, tesseract: str | None) -> str:
    """OCR a page with Tesseract, or Windows OCR when available."""
    hindi_required = page_number in HINDI_ONLY_PAGES.get(pdf_path.name, set())
    with tempfile.TemporaryDirectory(prefix="railassist-ocr-") as temp_dir:
        prefix = Path(temp_dir) / "page"
        rendered = subprocess.run(
            [renderer, "-f", str(page_number), "-l", str(page_number), "-r", "180", "-png", "-singlefile", str(pdf_path), str(prefix)],
            capture_output=True,
            timeout=60,
            check=False,
        )
        image_path = prefix.with_suffix(".png")
        if rendered.returncode != 0 or not image_path.exists():
            return ""

        if tesseract:
            languages = [os.getenv("RAILASSIST_OCR_LANG", "eng+hin"), "eng"]
            if hindi_required:
                languages = [language for language in languages if "hin" in language.lower()]
            for language in dict.fromkeys(languages):
                result = subprocess.run(
                    [tesseract, str(image_path), "stdout", "-l", language],
                    capture_output=True,
                    timeout=90,
                    check=False,
                )
                if result.returncode == 0:
                    text = result.stdout.decode("utf-8", errors="replace")
                    if text.strip():
                        return text

        # Windows' in-box OCR supports the installed Windows language pack only;
        # avoid indexing Hindi pages as English gibberish.
        if hindi_required:
            return ""

        powershell = shutil.which("powershell") or shutil.which("pwsh")
        ocr_script = Path(__file__).with_name("windows_ocr.ps1")
        if powershell and ocr_script.is_file():
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ocr_script), str(image_path)],
                capture_output=True,
                timeout=90,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.decode("utf-8", errors="replace")
        return ""


def _read_pdf(path: Path) -> tuple[list[tuple[int | None, str]], list[str]]:
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(str(path), strict=False)
    renderer = shutil.which("pdftoppm") or shutil.which("pdftocairo")
    tesseract = shutil.which("tesseract")
    windows_ocr_available = bool(shutil.which("powershell") or shutil.which("pwsh"))
    pages: list[tuple[int | None, str]] = []
    warnings: list[str] = []

    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = _clean_text(page.extract_text() or "")
        except Exception:
            text = ""
        if not text and renderer and (tesseract or windows_ocr_available):
            text = _clean_text(_ocr_page(path, page_number, renderer, tesseract))
        if not text:
            reason = "Hindi OCR language is unavailable" if page_number in HINDI_ONLY_PAGES.get(path.name, set()) else "no text layer or OCR text"
            warnings.append(f"{path.name}, page {page_number}: {reason}")
        else:
            pages.append((page_number, text))
    return pages, warnings


def _split_text(text: str, max_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text on paragraph boundaries, then use a small overlap if needed."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs or [text]:
        while len(paragraph) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            cut = paragraph.rfind(" ", 0, max_chars)
            if cut < max_chars // 2:
                cut = max_chars
            pieces.append(paragraph[:cut].strip())
            paragraph = paragraph[max(0, cut - overlap):].strip()
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                pieces.append(current)
            tail = current[-overlap:] if current else ""
            current = f"{tail} {paragraph}".strip()
    if current:
        pieces.append(current)
    return [piece for piece in pieces if piece]


def _source_fingerprint(data_dir: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(p for p in (data_dir / "documents").glob("*") if p.suffix.lower() in {".pdf", ".html", ".htm"})
    for path in files:
        stat = path.stat()
        digest.update(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8"))
    return digest.hexdigest()


def ingest_documents(data_dir: Path = DEFAULT_DATA_DIR) -> tuple[list[DocumentChunk], list[str]]:
    """Extract documents page by page and split them into source-aware chunks."""
    documents_dir = Path(data_dir) / "documents"
    if not documents_dir.is_dir():
        raise FileNotFoundError(
            f"Railway documents were not found at {documents_dir}. "
            "Unzip rail_capstone_pack.zip into data/rail_capstone_pack/."
        )

    chunks: list[DocumentChunk] = []
    warnings: list[str] = []
    files = sorted(p for p in documents_dir.iterdir() if p.suffix.lower() in {".pdf", ".html", ".htm"})
    if not files:
        raise FileNotFoundError(f"No PDF or HTML documents found in {documents_dir}.")

    for path in files:
        try:
            if path.suffix.lower() == ".pdf":
                pages, page_warnings = _read_pdf(path)
                warnings.extend(page_warnings)
            else:
                pages = _read_html(path)
            chunk_number = 0
            for page_number, text in pages:
                for content in _split_text(text):
                    chunks.append(DocumentChunk(
                        doc=path.name,
                        page=page_number,
                        date=DOCUMENT_DATES.get(path.name),
                        text=content,
                        chunk=chunk_number,
                    ))
                    chunk_number += 1
        except Exception as exc:
            warnings.append(f"{path.name}: extraction failed ({type(exc).__name__})")

    if not chunks:
        raise RuntimeError("No document text could be extracted from the railway data pack.")
    return chunks, warnings


def load_or_build_chunks(
    data_dir: Path = DEFAULT_DATA_DIR,
    index_path: Path = DEFAULT_INDEX_PATH,
    force: bool = False,
) -> tuple[list[DocumentChunk], list[str]]:
    """Load a fresh generated index or rebuild it from the supplied documents."""
    data_dir = Path(data_dir)
    index_path = Path(index_path)
    fingerprint = _source_fingerprint(data_dir)
    if not force and index_path.is_file():
        try:
            saved: dict[str, Any] = json.loads(index_path.read_text(encoding="utf-8"))
            if saved.get("version") == INDEX_VERSION and saved.get("fingerprint") == fingerprint:
                return [DocumentChunk(**item) for item in saved["chunks"]], list(saved.get("warnings", []))
        except (OSError, ValueError, TypeError, KeyError):
            pass

    chunks, warnings = ingest_documents(data_dir)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": INDEX_VERSION,
        "fingerprint": fingerprint,
        "warnings": warnings,
        "chunks": [asdict(chunk) for chunk in chunks],
    }
    index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return chunks, warnings
