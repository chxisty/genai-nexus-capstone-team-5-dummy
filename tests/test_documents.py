import json

from helpdesk.documents import load_or_build_chunks


def test_html_ingestion_keeps_source_name_and_null_page(tmp_path):
    data_dir = tmp_path / "pack"
    documents = data_dir / "documents"
    documents.mkdir(parents=True)
    (documents / "refund.html").write_text(
        "<html><head><title>Rules</title><script>ignore me</script></head>"
        "<body><h1>Refund rules</h1><p>Waitlisted tickets receive a refund.</p></body></html>",
        encoding="utf-8",
    )

    index_path = tmp_path / "index.json"
    chunks, warnings = load_or_build_chunks(data_dir, index_path)

    assert warnings == []
    assert len(chunks) == 1
    assert chunks[0].doc == "refund.html"
    assert chunks[0].page is None
    assert "Waitlisted tickets" in chunks[0].text
    assert "ignore me" not in chunks[0].text

    cached, _ = load_or_build_chunks(data_dir, index_path)
    assert cached == chunks
    assert json.loads(index_path.read_text(encoding="utf-8"))["version"] == 1
