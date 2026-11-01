"""Tests use the small made-up demo batch in test mode, not the snapshot of real data."""
import pytest


@pytest.fixture(autouse=True)
def _synthetic_demo(monkeypatch):
    monkeypatch.setenv("BRESAOLA_DEMO", "synthetic")
