"""Contrato jev-compat-v1: validação, erros padronizados e montagem das respostas (tarefas 37–40)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import jsonschema

CONTRACT_VERSION = "jev-compat-v1"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "contracts" / "jev" / "schemas"
# Piso numérico comum a todos os candidatos: o Laya arredonda em 4 casas e
# probabilidades exatamente 0 tornariam a log-loss infinita.
PROB_FLOOR = 1e-6


class JevError(Exception):
    status = 500
    error_type = "internal"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def body(self) -> dict:
        return {"detail": {"error_type": self.error_type, "message": self.message}}


class InvalidRequest(JevError):
    status = 422
    error_type = "invalid_request"


class ContextLimit(JevError):
    status = 422
    error_type = "context"


class UnknownOption(JevError):
    status = 502
    error_type = "unknown_option"


class ModelUnavailable(JevError):
    status = 503
    error_type = "unavailable"


@lru_cache(maxsize=None)
def _validator(name: str) -> jsonschema.Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
    return jsonschema.Draft202012Validator(schema)


def validate_request(request: dict) -> None:
    errors = sorted(_validator("request").iter_errors(request), key=lambda e: list(e.path))
    if errors:
        e = errors[0]
        where = "/".join(str(p) for p in e.path) or "<raiz>"
        raise InvalidRequest(f"{where}: {e.message}")


def response_errors(response: dict) -> list[str]:
    return [f"{'/'.join(map(str, e.path)) or '<raiz>'}: {e.message}"
            for e in _validator("response").iter_errors(response)]


def option_keys(question: dict) -> list[str]:
    """Chaves das opções na ordem declarada (tarefa 49)."""
    kind = question["type"]
    if kind == "choice":
        return list(question["criteria"])
    if kind == "noul":
        return ["true", "false"]
    return [str(i) for i in range(len(question["criteria"]))]


def option_descriptions(question: dict) -> dict[str, str]:
    kind = question["type"]
    if kind == "score":
        return {str(i): d for i, d in enumerate(question["criteria"])}
    return {k: question["criteria"][k] for k in option_keys(question)}


def normalize(probabilities: dict[str, float], keys: list[str]) -> dict[str, float]:
    """Mesmas chaves, mesma ordem, piso numérico e soma 1."""
    if set(probabilities) != set(keys):
        extra = sorted(set(probabilities) - set(keys))
        missing = sorted(set(keys) - set(probabilities))
        raise UnknownOption(f"opções divergentes: extras={extra} ausentes={missing}")
    clipped = {k: max(float(probabilities[k]), PROB_FLOOR) for k in keys}
    total = sum(clipped.values())
    return {k: v / total for k, v in clipped.items()}


def choice_answer(probabilities: dict[str, float], question: dict, confidence: float | None = None) -> dict:
    keys = option_keys(question)
    p = normalize(probabilities, keys)
    choice = max(keys, key=p.__getitem__)
    return {"type": "choice", "choice": choice,
            "confidence": float(confidence) if confidence is not None else p[choice],
            "probabilities": p}


def noul_answer(p_true: float) -> dict:
    p = min(max(float(p_true), PROB_FLOOR), 1 - PROB_FLOOR)
    return {"type": "noul", "noul": p}


def score_answer(probabilities: dict[str, float], question: dict, confidence: float | None = None) -> dict:
    keys = option_keys(question)
    p = normalize(probabilities, keys)
    best = max(keys, key=p.__getitem__)
    return {"type": "score", "score": sum(int(k) * v for k, v in p.items()),
            "confidence": float(confidence) if confidence is not None else p[best],
            "probabilities": p, "legend": option_descriptions(question)}


def answer_from_distribution(question: dict, probabilities: dict[str, float],
                             confidence: float | None = None) -> dict:
    """Monta a resposta JEV de qualquer tipo a partir de uma distribuição sobre option_keys()."""
    kind = question["type"]
    if kind == "choice":
        return choice_answer(probabilities, question, confidence)
    if kind == "noul":
        p = normalize(probabilities, ["true", "false"])
        return noul_answer(p["true"])
    return score_answer(probabilities, question, confidence)
