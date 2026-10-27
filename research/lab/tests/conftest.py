"""Every test gets its own trial registry (metrics.registry_path), so none ever appends to the lab's."""

import pytest


@pytest.fixture(autouse=True)
def _own_trial_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(tmp_path / "trials" / "registry.jsonl"))
