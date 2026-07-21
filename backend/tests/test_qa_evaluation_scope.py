from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "run_qa_faithfulness_v1",
    ROOT / "data" / "evaluation" / "run_qa_faithfulness_v1.py",
)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def test_historical_qa_evaluation_explicitly_uses_technical_scope(monkeypatch) -> None:
    captured: dict = {}

    def fake_ask_question(session, question, **kwargs):
        captured.update({"session": session, "question": question, **kwargs})
        return {"answer": "bounded"}

    monkeypatch.setattr(RUNNER, "ask_question", fake_ask_question)
    session = object()

    result = RUNNER.generate_evaluation_answer(
        session,
        {"question": "What evidence is present?"},
        mode="keyword",
        provider="offline_extractive",
        model=None,
        top_k=5,
        retrieval_scope="technical",
    )

    assert result == {"answer": "bounded"}
    assert captured["session"] is session
    assert captured["retrieval_scope"] == "technical"
    assert captured["persist"] is False
