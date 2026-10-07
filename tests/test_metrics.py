import pytest

from analysis.metrics import calibration, classification, latency_summary, selective

ROWS = [
    {"gold": "a", "pred": "a", "probabilities": {"a": 0.9, "b": 0.1}},
    {"gold": "a", "pred": "b", "probabilities": {"a": 0.4, "b": 0.6}},
    {"gold": "b", "pred": "b", "probabilities": {"a": 0.2, "b": 0.8}},
    {"gold": "b", "pred": None, "error": "timeout"},
]


def test_classification():
    m = classification(ROWS)
    assert m["n"] == 3 and m["errors"] == 1
    assert m["accuracy"] == pytest.approx(2 / 3)
    assert m["per_label"]["a"]["recall"] == pytest.approx(0.5)
    assert m["per_label"]["b"]["precision"] == pytest.approx(0.5)


def test_calibration_and_selective():
    c = calibration(ROWS)
    assert 0 <= c["ece"] <= 1 and c["brier"] > 0
    s = selective(ROWS, 0.7)
    assert s["coverage"] == pytest.approx(2 / 3) and s["selective_accuracy"] == 1.0


def test_latency():
    assert latency_summary([1, 2, 3, 4])["p50"] == pytest.approx(2.5)
