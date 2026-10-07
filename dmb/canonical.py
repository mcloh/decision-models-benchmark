"""Formato canônico, serialização do estado e conversão para JEV (tarefas 36, 53 e 54)."""
from __future__ import annotations

from typing import Callable, Iterator

from .jev import validate_request

SERIALIZATION_VERSION = "state-text-v1"


def iter_questions(example: dict) -> Iterator[dict]:
    """Um exemplo traz uma pergunta (campos na raiz) ou várias (`questions`, tarefa 65)."""
    if "questions" in example:
        yield from example["questions"]
    else:
        yield {k: example[k] for k in ("question", "question_type", "options", "gold_label") if k in example} | {
            "name": example["task"]}


def serialize_state(state: dict, utterance: str, n_turns: int) -> str:
    """Regra única de serialização para todos os candidatos (state-text-v1)."""
    lines = ["Contexto:",
             f"Agente ativo: {state.get('active_agent') or 'nenhum'}"]
    suspended = state.get("suspended_sessions") or []
    lines.append("Sessões suspensas: " + (", ".join(suspended) if suspended else "nenhuma"))
    turns = (state.get("recent_turns") or [])[-n_turns:] if n_turns > 0 else []
    if turns:
        lines.append("Turnos anteriores:")
        for t in turns:
            who = "Usuário" if t["role"] == "user" else f"Agente ({t.get('agent_id', '?')})"
            lines.append(f"- {who}: {t['text']}")
    lines += ["", f"Mensagem: {utterance}"]
    return "\n".join(lines)


def fit_state(state: dict, utterance: str, n_turns: int, budget: int,
              count_tokens: Callable[[str], int]) -> tuple[str, dict]:
    """Truncamento comum: descarta primeiro os turnos mais antigos; o enunciado só é
    cortado no fim se sozinho estourar o orçamento."""
    for n in range(n_turns, -1, -1):
        text = serialize_state(state, utterance, n)
        tokens = count_tokens(text)
        if tokens <= budget:
            return text, {"turns_used": n, "tokens": tokens, "truncated": n < n_turns}
    lo, hi = 0, len(utterance)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_tokens(serialize_state(state, utterance[:mid], 0)) <= budget:
            lo = mid
        else:
            hi = mid - 1
    text = serialize_state(state, utterance[:lo], 0)
    return text, {"turns_used": 0, "tokens": count_tokens(text), "truncated": True,
                  "utterance_chars_kept": lo}


def jev_question(q: dict) -> dict:
    kind = q.get("question_type", "choice")
    if kind == "score":
        criteria = list(q["options"].values()) if isinstance(q["options"], dict) else list(q["options"])
    else:
        criteria = dict(q["options"])
    return {"type": kind, "instructions": q["question"], "criteria": criteria}


def to_jev_request(example: dict, model: str, n_turns: int, budget: int | None = None,
                   count_tokens: Callable[[str], int] | None = None) -> tuple[dict, dict]:
    if budget is not None and count_tokens is not None:
        state, info = fit_state(example["state"], example["utterance"], n_turns, budget, count_tokens)
    else:
        state, info = serialize_state(example["state"], example["utterance"], n_turns), {"truncated": False}
    request = {"model": model, "state": state,
               "questions": {q["name"]: jev_question(q) for q in iter_questions(example)}}
    validate_request(request)
    info["serialization"] = SERIALIZATION_VERSION
    return request, info
