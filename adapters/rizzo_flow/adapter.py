"""Adaptador do Rizzo Flow 4B (GGUF Q8_0 sobre llama.cpp) com prompts spark-decisions-v3 (tarefa 45)."""
from __future__ import annotations

from pathlib import Path

from dmb.adapter import Adapter
from dmb.jev import ContextLimit, answer_from_distribution, option_keys

GGUF_FILE = "spark-x2.5-4b-rizzo-flow-lora-q8_0.gguf"


class RizzoFlowAdapter(Adapter):
    name = "rizzo_flow"
    probabilities_source = "native"

    def __init__(self, *args, runtime_dir: str | Path | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.runtime_dir = runtime_dir

    def load(self) -> None:
        from rizzo_flow.backend_llama import LlamaBackend
        from rizzo_flow.compat import model_name
        from rizzo_flow.engine import Engine

        device = "cuda" if self.device == "cuda" else ("cpu" if self.device == "cpu" else "auto")
        backend = LlamaBackend.load(self.model_dir / GGUF_FILE, device=device, ctx=self.context_limit,
                                    runtime_dir=self.runtime_dir)
        self.engine = Engine(backend, ctx=self.context_limit)
        self.served = model_name(backend.metadata)

    def native_context_limit(self) -> int:
        return 2048  # comprimento máximo dos prompts de treino do LoRA

    def count_tokens(self, text: str) -> int:
        return len(self.engine.backend.tokenizer.encode(text))

    def decide(self, state: str, questions: dict) -> tuple[dict, int]:
        from rizzo_flow.compat import SystemOneRequest, from_native, to_native

        request = SystemOneRequest.model_validate(
            {"model": self.served, "state": state, "questions": questions})
        native, options = to_native(request)
        try:
            raw = from_native(request, self.engine.decide(native), options, self.served)
        except ValueError as error:
            if "context" in str(error).lower() or "tokens" in str(error).lower():
                raise ContextLimit(str(error)) from error
            raise
        raw = raw if isinstance(raw, dict) else raw.model_dump()
        answers = {}
        for name, question in questions.items():
            a = raw["answers"][name]
            if question["type"] == "noul":
                p = float(a["noul"])
                dist = {"true": p, "false": 1 - p}
            else:
                dist = {k: a["probabilities"][k] for k in option_keys(question)}
            answers[name] = answer_from_distribution(question, dist, a.get("confidence"))
        return answers, int(raw.get("usage", {}).get("input_tokens", 0))
