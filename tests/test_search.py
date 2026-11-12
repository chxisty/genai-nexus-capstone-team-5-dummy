from helpdesk.documents import DocumentChunk
from helpdesk.search import BM25Search


def test_search_prefers_exact_code_and_relevant_passage():
    chunks = [
        DocumentChunk("tatkal.pdf", 1, "2025-06-10", "Tatkal booking requires Aadhaar authentication.", 0),
        DocumentChunk("refund.pdf", 2, "2026-01-19", "A confirmed ticket can be cancelled before departure.", 0),
        DocumentChunk("chart.pdf", 1, "2025-07-02", "Reservation charts are prepared before departure.", 0),
    ]

    hits = BM25Search(chunks).search("Tatkal Aadhaar", limit=2)

    assert hits[0].chunk.doc == "tatkal.pdf"
    assert len(hits) == 1
    assert hits[0].score > 0


def test_generic_train_question_does_not_match_policy_documents():
    chunks = [
        DocumentChunk("refund.pdf", 1, "2026-01-19", "Cancellation charges apply to a confirmed ticket.", 0),
    ]

    assert BM25Search(chunks).search("What is the name of train 12430?") == []
