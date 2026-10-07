import json
from pathlib import Path

import pytest

from dmb import jev

FIXTURES = Path(__file__).resolve().parents[1] / "contracts" / "jev" / "fixtures"
CASES = json.loads((FIXTURES / "conformance.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_request_fixtures(case):
    if case["expect"] == "ok":
        jev.validate_request(case["request"])
    else:
        with pytest.raises(jev.InvalidRequest):
            jev.validate_request(case["request"])


def test_normalize_keeps_declared_order_and_floor():
    p = jev.normalize({"b": 0.0, "a": 1.0}, ["a", "b"])
    assert list(p) == ["a", "b"]
    assert p["b"] > 0 and abs(sum(p.values()) - 1) < 1e-12


def test_normalize_rejects_unknown_option():
    with pytest.raises(jev.UnknownOption):
        jev.normalize({"a": 0.5, "z": 0.5}, ["a", "b"])


def test_answers_match_response_schema():
    choice_q = {"type": "choice", "instructions": "?", "criteria": {"a": "A", "b": "B"}}
    score_q = {"type": "score", "instructions": "?", "criteria": ["baixa", "alta"]}
    response = {
        "model": "m",
        "answers": {
            "c": jev.choice_answer({"a": 0.2, "b": 0.8}, choice_q),
            "n": jev.noul_answer(1.0),
            "s": jev.score_answer({"0": 0.25, "1": 0.75}, score_q),
        },
        "usage": {"input_tokens": 3, "output_tokens": 0},
    }
    assert jev.response_errors(response) == []
    assert response["answers"]["c"]["choice"] == "b"
    assert response["answers"]["s"]["score"] == pytest.approx(0.75)
    assert response["answers"]["n"]["noul"] < 1


def test_output_tokens_must_be_zero():
    response = {"model": "m", "answers": {"n": jev.noul_answer(0.5)},
                "usage": {"input_tokens": 1, "output_tokens": 5}}
    assert jev.response_errors(response)
