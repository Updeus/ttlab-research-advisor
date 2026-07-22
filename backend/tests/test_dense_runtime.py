from app.indexing import dense_runtime


class FakeDenseProvider:
    def embed(self, text: str) -> list[float]:
        assert "warmup" in text
        return [1.0]


def test_dense_runtime_reports_ready_after_successful_warmup(monkeypatch) -> None:
    monkeypatch.setattr(dense_runtime, "_state", "warming")
    monkeypatch.setattr(dense_runtime, "_started_at", "2026-01-01T00:00:00+00:00")
    monkeypatch.setattr(dense_runtime, "_ready_at", None)
    monkeypatch.setattr(dense_runtime, "_elapsed_seconds", None)
    monkeypatch.setattr(dense_runtime, "get_provider", lambda _name: FakeDenseProvider())

    dense_runtime.warm_dense_provider()

    diagnostics = dense_runtime.dense_runtime_diagnostics()
    assert diagnostics["state"] == "ready"
    assert diagnostics["ready_at"] is not None
    assert isinstance(diagnostics["elapsed_seconds"], float)
