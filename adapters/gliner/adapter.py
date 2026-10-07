"""Adaptador do GLiNER2.5-multi-Decide via classify_text (tarefa 44).

O GLiNER devolve só o rótulo vencedor no modo de rótulo único. Para obter a
distribuição completa, cada pergunta é enviada com `multi_label=True`,
`class_act="softmax"` e `cls_threshold=0`: o modelo calcula o mesmo softmax do modo
de rótulo único e devolve todas as opções com sua probabilidade.
"""
from __future__ import annotations

from dmb.adapter import Adapter
from dmb.jev import ContextLimit, answer_from_distribution, option_descriptions


class GlinerAdapter(Adapter):
    name = "gliner"
    probabilities_source = "native"

    def load(self) -> None:
        from gliner2 import AutoExtractor
        from tokenizers import Tokenizer

        self.model = AutoExtractor.from_pretrained(str(self.model_dir))
        if self.device not in ("auto", "cpu"):
            self.model.to(self.device)
        elif self.device == "auto":
            import torch
            if torch.cuda.is_available():
                self.model.to("cuda")
        self.model.eval()
        self.tokenizer = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))

    def native_context_limit(self) -> int:
        return int(getattr(self.model.config, "max_len", 512) or 512)

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)

    def decide(self, state: str, questions: dict) -> tuple[dict, int]:
        tokens = self.count_tokens(state)
        if tokens > self.context_limit:
            raise ContextLimit(f"{tokens} tokens > limite {self.context_limit}")
        # As instruções entram como prefixo do texto: o classify_text não tem campo de pergunta.
        answers = {}
        for name, question in questions.items():
            labels = option_descriptions(question)
            text = f"Pergunta: {question['instructions']}\n{state}"
            raw = self.model.classify_text(
                text,
                {name: {"labels": labels, "multi_label": True, "class_act": "softmax",
                        "cls_threshold": 0.0}},
                include_confidence=True,
            )[name]
            dist = {item["label"]: item["confidence"] for item in raw}
            answers[name] = answer_from_distribution(question, dist)
        return answers, tokens
