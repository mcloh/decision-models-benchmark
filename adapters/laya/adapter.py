"""Adaptador do Laya multilingual (tarefa 42)."""
from __future__ import annotations

from pathlib import Path

from dmb.adapter import Adapter
from dmb.jev import ContextLimit, answer_from_distribution, option_keys


class LayaAdapter(Adapter):
    name = "laya"
    # Laya arredonda as probabilidades em 4 casas; o piso comum de dmb.jev cobre os zeros.
    probabilities_source = "native"

    def load(self) -> None:
        import shutil
        import tempfile

        import laya
        from tokenizers import Tokenizer

        # laya.load() regrava tokenizer/tokenizer_config.json no próprio diretório
        # (_fix_tokenizer_config). Carregamos de uma cópia para não alterar os artefatos verificados.
        self._workdir = Path(tempfile.mkdtemp(prefix="dmb-laya-")) / "model"
        shutil.copytree(self.model_dir, self._workdir)
        self.agent = laya.load(str(self._workdir))
        self.tokenizer = Tokenizer.from_file(str(self.model_dir / "tokenizer" / "tokenizer.json"))

    @property
    def head_max_len(self) -> int | None:
        """Orçamento de tokens da pergunta + opções (padrão do checkpoint: 192). Parâmetro operacional."""
        import os
        value = os.environ.get("DMB_LAYA_HEAD_MAX_LEN")
        return int(value) if value else None

    def native_context_limit(self) -> int:
        return 1024  # padrão do checkpoint; 256 desses tokens vão para pergunta + opções

    def count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)

    def decide(self, state: str, questions: dict) -> tuple[dict, int]:
        result = self.agent.predict(state, questions, max_len=self.context_limit,
                                    head_max_len=self.head_max_len)
        usage = result.get("usage", {})
        if usage.get("truncated") or usage.get("state_tokens_dropped"):
            raise ContextLimit(f"Laya truncou o estado: {usage}")
        if usage.get("options"):
            # Opções que perderam a descrição própria por falta de orçamento de cabeçalho.
            self.last_diagnostics = {"collapsed_options": usage["options"], "head_max_len": self.head_max_len}
        answers = {}
        for name, question in questions.items():
            raw = result["answers"][name]
            if question["type"] == "noul":
                p = float(raw["noul"])
                dist = {"true": p, "false": 1 - p}
            else:
                dist = raw["probabilities"]
                if question["type"] == "score":
                    dist = {k: dist[k] for k in option_keys(question)}
            answers[name] = answer_from_distribution(question, dist, raw.get("confidence"))
        return answers, int(usage.get("input_tokens", 0))
