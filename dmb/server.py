"""Servidor local POST /v1/systemone, idêntico para todos os candidatos (tarefas 46–48, 50)."""
from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .adapter import Adapter
from .jev import (CONTRACT_VERSION, InvalidRequest, JevError, ModelUnavailable, UnknownOption,
                  option_keys, response_errors, validate_request)


def build_response(adapter: Adapter, request: dict, answers: dict, input_tokens: int,
                   latency_ms: float) -> dict:
    if list(answers) != list(request["questions"]):
        raise UnknownOption(f"perguntas respondidas {list(answers)} != {list(request['questions'])}")
    for name, question in request["questions"].items():
        answer = answers[name]
        if answer.get("type") != question["type"]:
            raise UnknownOption(f"{name}: tipo {answer.get('type')} != {question['type']}")
        if question["type"] in ("choice", "score"):
            keys = option_keys(question)
            if list(answer["probabilities"]) != keys:
                raise UnknownOption(f"{name}: ordem ou chaves das opções alteradas")
            if question["type"] == "choice" and answer["choice"] not in keys:
                raise UnknownOption(f"{name}: escolha {answer['choice']!r} fora de criteria")
    response = {
        "model": adapter.model_id,
        "answers": answers,
        "usage": {"input_tokens": int(input_tokens), "output_tokens": 0},
        "metadata": {
            "latency_ms": latency_ms,
            "model_id": adapter.model_id,
            "run_id": os.environ.get("DMB_RUN_ID", "local"),
            "adapter_version": adapter.adapter_version,
            "contract_version": CONTRACT_VERSION,
            "probabilities_source": adapter.probabilities_source,
        },
    }
    errors = response_errors(response)
    if errors:
        raise UnknownOption("resposta fora do contrato: " + "; ".join(errors[:3]))
    return response


def systemone(adapter: Adapter, request: dict) -> dict:
    """Caminho único usado pelo HTTP e pelo harness em processo."""
    validate_request(request)
    state = request["state"]
    if not isinstance(state, str):
        # Todo adaptador recebe texto; estados estruturados viram JSON canônico.
        state = json.dumps(state, ensure_ascii=False, sort_keys=True)
    started = time.perf_counter()
    answers, input_tokens = adapter.decide(state, request["questions"])
    latency_ms = (time.perf_counter() - started) * 1000
    return build_response(adapter, request, answers, input_tokens, latency_ms)


def create_app(adapter: Adapter) -> FastAPI:
    state = {"ready": False}

    @asynccontextmanager
    async def lifespan(_app):
        started = time.perf_counter()
        adapter.load()
        state.update(ready=True, load_seconds=time.perf_counter() - started)
        yield

    app = FastAPI(title=f"dmb {adapter.name}", version=adapter.adapter_version, lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ready" if state["ready"] else "loading", **adapter.describe(),
                "load_seconds": state.get("load_seconds")}

    @app.post("/v1/systemone")
    async def endpoint(http_request: Request):
        try:
            try:
                body = await http_request.json()
            except ValueError as error:
                raise InvalidRequest(f"JSON inválido: {error}") from error
            if not state["ready"]:
                raise ModelUnavailable("modelo ainda carregando")
            return systemone(adapter, body)
        except JevError as error:
            return JSONResponse(status_code=error.status, content=error.body())

    return app
