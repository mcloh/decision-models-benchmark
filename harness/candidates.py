"""Construção dos adaptadores a partir do manifesto de artefatos."""
from __future__ import annotations

import json
from pathlib import Path

from adapters import adapter_class

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "env" / "artifacts-manifest.json"
MODEL_REPO = {
    "laya": "convaiinnovations/laya-multilingual",
    "semif": "Qwen/Qwen3.5-4B",
    "gliner": "fastino/GLiNER2.5-multi-Decide",
    "rizzo_flow": "rizzoaiacademy/rizzo-flow",
}


def model_location(candidate: str, models_root: Path) -> tuple[Path, str]:
    """Diretório local e revisão fixada do candidato, segundo o manifesto."""
    manifest = json.loads(MANIFEST.read_text())
    repo = MODEL_REPO[candidate]
    entry = next(a for a in manifest["artifacts"]
                 if a["candidate"] == candidate and a["kind"] == "hf_model" and a["origin"] == f"hf://{repo}")
    rev = entry["revision"]
    return models_root / candidate / repo.replace("/", "__") / rev, rev


def build_adapter(candidate: str, models_root: str | Path, device: str = "auto",
                  context_limit: int | None = None, **extra):
    model_dir, revision = model_location(candidate, Path(models_root))
    return adapter_class(candidate)(model_dir, revision, device=device,
                                    context_limit=context_limit, **extra)
