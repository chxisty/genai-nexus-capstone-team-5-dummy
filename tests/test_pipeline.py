from helpdesk.documents import DocumentChunk
from helpdesk.pipeline import _format_result, ask as ask_question
from helpdesk.search import SearchHit


def test_final_result_accepts_only_retrieved_citations():
    hit = SearchHit(DocumentChunk("refund.pdf", 3, "2026-01-19", "Clerkage is charged.", 0), 4.0)
    result = _format_result(
        '{"answer":"A clerkage charge applies.","sources":[{"doc":"refund.pdf","page":3},{"doc":"fake.pdf","page":99}],"dont_know":false}',
        [hit],
        None,
        False,
    )

    assert result["answer"] == "A clerkage charge applies."
    assert result["sources"] == [{"doc": "refund.pdf", "page": 3}]
    assert result["sql"] is None
    assert result["dont_know"] is False


def test_missing_evidence_forces_dont_know():
    result = _format_result(
        '{"answer":"The live status is on time.","sources":[],"dont_know":false}',
        [],
        None,
        False,
    )

    assert result["dont_know"] is True
    assert "I don't know" in result["answer"]


def test_ask_returns_structured_answer_with_grounded_citation(monkeypatch):
    from helpdesk import pipeline
    from helpdesk.search import BM25Search

    hit_chunk = DocumentChunk("refund.pdf", 3, "2026-01-19", "A clerkage charge applies to waitlisted tickets.", 0)

    class FakeMessage:
        content = '{"answer":"A clerkage charge applies.","sources":[{"doc":"refund.pdf","page":3}],"sql":null,"dont_know":false}'
        tool_calls = None

    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return type("Response", (), {"choices": [type("Choice", (), {"message": FakeMessage()})()]})()

    monkeypatch.setattr(pipeline, "_get_search", lambda: (BM25Search([hit_chunk]), []))
    monkeypatch.setattr(pipeline, "_get_client", lambda: FakeClient())
    monkeypatch.setattr(pipeline, "reset_conversation", lambda: pipeline._conversation.clear())
    pipeline.reset_conversation()

    result = ask_question("How much is charged for a waitlisted ticket?")

    assert result["answer"] == "A clerkage charge applies."
    assert result["sources"] == [{"doc": "refund.pdf", "page": 3}]
    assert result["sql"] is None
    assert result["dont_know"] is False


def test_ask_runs_sql_tool_and_returns_exact_sql(monkeypatch):
    import json
    from helpdesk import pipeline
    from helpdesk.search import BM25Search

    sql = "SELECT number, name FROM trains WHERE number = '12430'"

    class Function:
        name = "run_timetable_query"
        arguments = json.dumps({"sql": sql})

    class ToolCall:
        id = "tool-1"
        function = Function()

    class ToolMessage:
        content = None
        tool_calls = [ToolCall()]

        def model_dump(self, exclude_none=True):
            return {"role": "assistant", "tool_calls": []}

    class FinalMessage:
        content = '{"answer":"Train 12430 is listed in the timetable.","sources":[],"dont_know":false}'
        tool_calls = None

    class FakeClient:
        def __init__(self):
            self.responses = [ToolMessage(), FinalMessage()]
            self.chat = type("Chat", (), {})()
            self.chat.completions = type("Completions", (), {"create": self.create})()

        def create(self, **kwargs):
            message = self.responses.pop(0)
            return type("Response", (), {"choices": [type("Choice", (), {"message": message})()]})()

    fake = FakeClient()
    monkeypatch.setattr(pipeline, "_get_search", lambda: (BM25Search([]), []))
    monkeypatch.setattr(pipeline, "_get_client", lambda: fake)
    pipeline.reset_conversation()

    result = pipeline.ask("What is the name of train 12430?")

    assert result["answer"] == "Train 12430 is listed in the timetable."
    assert result["sql"] == sql
    assert result["sources"] == []
    assert result["dont_know"] is False
