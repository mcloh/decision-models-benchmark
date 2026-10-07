"""Adaptador do SemIf (modo direct) com Qwen3.5-4B fixado (tarefa 43)."""
from __future__ import annotations

from dmb.adapter import Adapter
from dmb.jev import ContextLimit, answer_from_distribution, option_descriptions


class SemIfAdapter(Adapter):
    name = "semif"
    probabilities_source = "native"

    def load(self) -> None:
        from semif_phase1 import core, direct

        dev = self.device
        if dev == "auto":
            import torch
            dev = "cuda" if torch.cuda.is_available() else "cpu"
        self._direct = direct
        self.model, self.tokenizer, self.metadata = core.load_causal_model(
            str(self.model_dir), self.revision, device=dev, dtype="bfloat16")

    def native_context_limit(self) -> int:
        return 8192

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def decide(self, state: str, questions: dict) -> tuple[dict, int]:
        answers, total_tokens = {}, 0
        for name, question in questions.items():
            options = option_descriptions(question)
            row = {"id": name, "state": state, "question": question["instructions"],
                   "options": [{"id": k, "description": v} for k, v in options.items()]}
            try:
                out = self._direct.score(self.model, self.tokenizer, row, self.metadata,
                                         max_tokens=self.context_limit)
            except ValueError as error:
                if "exceed limit" in str(error):
                    raise ContextLimit(str(error)) from error
                raise
            dist = dict(zip(out["option_ids"], out["probabilities"]))
            answers[name] = answer_from_distribution(question, dist)
            total_tokens += out["input_tokens"]
        return answers, total_tokens
