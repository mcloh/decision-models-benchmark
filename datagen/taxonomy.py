"""Leitura da taxonomia e do guia de anotação."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "data" / "taxonomy" / "intents-v1.yaml"
GUIDE = ROOT / "docs" / "06-guia-de-anotacao.md"


@lru_cache(maxsize=None)
def load() -> dict:
    raw = yaml.safe_load(TAXONOMY.read_text())
    intents = {}
    for domain, items in raw["domains"].items():
        for it in items:
            intents[it["id"]] = {"domain": domain, "description": it["description"],
                                 "confusable_with": it.get("confusable_with", [])}
    return {"version": raw["version"], "fallback": raw["fallback"], "intents": intents,
            "out_of_scope": {o["id"]: o["description"] for o in raw["out_of_scope"]}}


def guide() -> str:
    text = GUIDE.read_text()
    return text.split("<!-- GUIA:INICIO -->")[1].split("<!-- GUIA:FIM -->")[0].strip()


def taxonomy_block() -> str:
    t = load()
    lines = [f"- `{k}` ({v['domain']}): {v['description']}" for k, v in t["intents"].items()]
    lines.append(f"- `{t['fallback']['id']}`: {t['fallback']['description']}")
    return "\n".join(lines)


def labels() -> set[str]:
    t = load()
    return set(t["intents"]) | {t["fallback"]["id"]}
