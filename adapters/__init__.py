"""Adaptadores JEV locais. Cada candidato roda num ambiente próprio (dependências incompatíveis)."""
from importlib import import_module

REGISTRY = {
    "laya": "adapters.laya.adapter:LayaAdapter",
    "semif": "adapters.semif.adapter:SemIfAdapter",
    "gliner": "adapters.gliner.adapter:GlinerAdapter",
    "rizzo_flow": "adapters.rizzo_flow.adapter:RizzoFlowAdapter",
}


def adapter_class(name: str):
    module, cls = REGISTRY[name].split(":")
    return getattr(import_module(module), cls)
