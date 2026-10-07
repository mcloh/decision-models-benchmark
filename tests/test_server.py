import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dmb.adapter import Adapter
from dmb.jev import answer_from_distribution, option_descriptions, response_errors
from dmb.server import create_app

FIXTURES = Path(__file__).resolve().parents[1] / "contracts" / "jev" / "fixtures"
CASES = json.loads((FIXTURES / "conformance.json").read_text())["cases"]


class FakeAdapter(Adapter):
    """Escolhe a opção cuja descrição compartilha mais palavras com o estado."""
    name = "fake"

    def load(self):
        pass

    def native_context_limit(self):
        return 10_000

    def count_tokens(self, text):
        return len(text.split())

    def decide(self, state, questions):
        words = set(str(state).lower().split())
        answers = {}
        for name, q in questions.items():
            scores = {k: 1 + len(words & set(d.lower().split())) for k, d in option_descriptions(q).items()}
            total = sum(scores.values())
            answers[name] = answer_from_distribution(q, {k: v / total for k, v in scores.items()})
        return answers, self.count_tokens(str(state))


class BrokenAdapter(FakeAdapter):
    def decide(self, state, questions):
        answers, n = super().decide(state, questions)
        for a in answers.values():
            if "probabilities" in a:
                a["probabilities"] = dict(reversed(list(a["probabilities"].items())))
        return answers, n


@pytest.fixture
def client():
    with TestClient(create_app(FakeAdapter("unused", "0" * 40))) as c:
        yield c


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_conformance(client, case):
    r = client.post("/v1/systemone", json=case["request"])
    if case["expect"] == "ok":
        assert r.status_code == 200, r.text
        body = r.json()
        assert response_errors(body) == []
        assert list(body["answers"]) == list(case["request"]["questions"])
        for name, q in case["request"]["questions"].items():
            if q["type"] == "choice":
                assert list(body["answers"][name]["probabilities"]) == list(q["criteria"])
        assert body["usage"]["output_tokens"] == 0
        assert {"latency_ms", "model_id", "run_id", "adapter_version"} <= body["metadata"].keys()
    else:
        assert r.status_code == 422
        assert r.json()["detail"]["error_type"] == "invalid_request"


def test_malformed_json(client):
    r = client.post("/v1/systemone", content=b"{nope", headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_reordered_options_are_rejected():
    with TestClient(create_app(BrokenAdapter("unused", "0" * 40))) as c:
        r = c.post("/v1/systemone", json=CASES[0]["request"])
    assert r.status_code == 502
    assert r.json()["detail"]["error_type"] == "unknown_option"


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ready" and body["name"] == "fake"
