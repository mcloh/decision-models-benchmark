import json
from pathlib import Path

import pytest

from analysis.calibrate import apply_temperature, choose_threshold, fit_temperature

ROOT = Path(__file__).resolve().parents[1]


def test_temperature_preserves_ranking_and_sums_to_one():
    p = {"a": 0.7, "b": 0.2, "c": 0.1}
    q = apply_temperature(p, 2.0)
    assert sum(q.values()) == pytest.approx(1.0)
    assert max(q, key=q.get) == "a" and q["a"] < p["a"]  # T > 1 suaviza


def test_fit_softens_overconfident_model():
    rows = [{"gold": "a", "probabilities": {"a": 0.99, "b": 0.01}}] * 6 + \
           [{"gold": "b", "probabilities": {"a": 0.99, "b": 0.01}}] * 4
    assert fit_temperature(rows) > 1.0


def test_threshold_respects_risk():
    rows = [{"gold": "a", "pred": "a", "probabilities": {"a": 0.9, "b": 0.1}}] * 98 + \
           [{"gold": "b", "pred": "a", "probabilities": {"a": 0.6, "b": 0.4}}] * 2 + \
           [{"gold": "b", "pred": "a", "probabilities": {"a": 0.95, "b": 0.05}}] * 1
    s = choose_threshold(rows)
    assert s["confident_wrong_rate"] <= 0.02


def test_frozen_files_unchanged():
    """Depois do congelamento (tarefa 62), nada do que foi congelado pode mudar."""
    frozen = ROOT / "config" / "frozen.json"
    if not frozen.exists():
        pytest.skip("configuração ainda não congelada")
    from tools.freeze import current_hashes
    assert current_hashes() == json.loads(frozen.read_text())["files"]
