"""Interface comum dos adaptadores JEV locais (tarefas 42–47)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Adapter(ABC):
    """Um candidato servido atrás de POST /v1/systemone.

    `decide` recebe o estado já serializado (texto) e as perguntas no formato JEV e
    devolve as respostas JEV de cada pergunta, mais o total de tokens de entrada.
    """

    name: str
    adapter_version = "0.2.0"
    # Diagnósticos da última decisão (ex.: opções truncadas pelo modelo); vão para metadata.diagnostics.
    last_diagnostics: dict = {}
    probabilities_source = "native"

    def __init__(self, model_dir: str | Path, revision: str, device: str = "auto",
                 context_limit: int | None = None):
        self.model_dir = Path(model_dir)
        self.revision = revision
        self.device = device
        self._context_limit = context_limit

    @property
    def model_id(self) -> str:
        return f"{self.name}@{self.revision[:12]}"

    @property
    def context_limit(self) -> int:
        return self._context_limit or self.native_context_limit()

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def native_context_limit(self) -> int: ...

    @abstractmethod
    def count_tokens(self, text: str) -> int: ...

    @abstractmethod
    def decide(self, state: str, questions: dict) -> tuple[dict, int]: ...

    def describe(self) -> dict:
        return {"name": self.name, "model_id": self.model_id, "revision": self.revision,
                "adapter_version": self.adapter_version, "device": self.device,
                "context_limit": self.context_limit,
                "probabilities_source": self.probabilities_source}
