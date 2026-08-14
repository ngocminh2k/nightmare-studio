import pytest


@pytest.fixture(autouse=True)
def use_deterministic_llm_in_tests(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_LLM_MODE", "mock")
