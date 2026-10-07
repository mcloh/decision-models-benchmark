"""Montagem do conjunto D1: partições, conjuntos de opções, lint e congelamento (tarefas 33–36).

- Partição por `group_id` (lote de geração), estratificada pelo alvo de geração:
  intenções (7 lotes) → 3 teste / 2 calibração / 2 desenvolvimento; fora de escopo (9 lotes) → 4 / 2 / 3.
- Conjunto de opções por exemplo (simula o serviço de elegibilidade): k ∈ {4, 8, 12, 16} opções
  incluindo `sem_correspondencia` (sempre a última). Distratores: confundíveis → mesmo domínio → aleatórios.
  Em 10% dos exemplos dentro do escopo a intenção correta fica fora das opções (rótulo vira
  `sem_correspondencia`, `gold_eligible=false`), para medir a abstenção.
- Congelamento: SHA-256 de cada partição em data/splits/MANIFEST.json; cópia em dmb-entrada e dmb-logs-imutaveis.

Uso: python -m datagen.build --run /data/runs/datagen-v1 [--freeze]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from datagen import taxonomy

ROOT = Path(__file__).resolve().parents[1]
SPLITS_DIR = ROOT / "data" / "splits"
SEED = 20261007
K_CHOICES = [4, 8, 12, 16]
P_GOLD_EXCLUDED = 0.10
QUESTION = "Qual é a intenção principal do cliente na Mensagem?"
MAX_OPTIONS = 16
FALLBACK = "sem_correspondencia"
SPLIT_PATTERN = {"intent": ["test"] * 3 + ["calibration"] * 2 + ["dev"] * 2,
                 "oos": ["test"] * 4 + ["calibration"] * 2 + ["dev"] * 3}


def assign_splits(rows: list[dict]) -> dict[str, str]:
    groups = defaultdict(set)
    kind = {}
    for r in rows:
        groups[r["gen_target"]].add(r["group_id"])
        kind[r["gen_target"]] = r["kind"]
    out = {}
    for target, gids in sorted(groups.items()):
        gids = sorted(gids)
        random.Random(f"{SEED}-{target}").shuffle(gids)
        pattern = SPLIT_PATTERN[kind[target]]
        for i, g in enumerate(gids):
            out[g] = pattern[i % len(pattern)]
    return out


def option_set(row: dict) -> tuple[dict, str, bool]:
    tax = taxonomy.load()
    intents = tax["intents"]
    rng = random.Random(f"{SEED}-{row['id']}")
    k = K_CHOICES[int(hashlib.sha256(row["id"].encode()).hexdigest(), 16) % len(K_CHOICES)]
    gold = row["gold_label"]
    in_scope = gold != FALLBACK
    include_gold = in_scope and rng.random() >= P_GOLD_EXCLUDED
    chosen = [gold] if include_gold else []
    pool = []
    if in_scope:
        pool += [c for c in intents[gold]["confusable_with"] if c != gold]
        pool += [i for i, v in intents.items() if v["domain"] == intents[gold]["domain"] and i != gold]
    rest = [i for i in intents if i != gold]
    rng.shuffle(rest)
    pool += rest
    for c in pool:
        if len(chosen) >= k - 1:
            break
        if c not in chosen and c != gold:
            chosen.append(c)
    rng.shuffle(chosen)
    options = {c: intents[c]["description"] for c in chosen}
    options[FALLBACK] = tax["fallback"]["description"]
    label = gold if include_gold else FALLBACK
    return options, label, include_gold or not in_scope


def to_example(row: dict, split: str) -> dict:
    options, label, eligible = option_set(row)
    return {
        "id": f"{row['id']}-D1", "group_id": row["group_id"], "task": "D1", "split": split,
        "state": {"active_agent": None, "suspended_sessions": [], "recent_turns": []},
        "utterance": row["text"], "question": QUESTION, "question_type": "choice",
        "options": options, "gold_label": label,
        "metadata": {
            "taxonomy_version": row["taxonomy_version"], "source": "synthetic",
            "intent_gold": row["gold_label"], "gold_eligible": eligible,
            "domain": taxonomy.load()["intents"].get(row["gold_label"], {}).get("domain", "fora_de_escopo"),
            "kind": row["kind"], "oos_category": row["gen_target"] if row["kind"] == "oos" else None,
            "profile": row["profile"], "sentiment": row.get("sentiment"),
            "secondary": row.get("secondary", []), "ambiguity": row.get("ambiguity"),
            "annotation": row["annotation"], "gen_agreement": row["gen_agreement"],
            "generator": row["generator"], "n_options": len(options),
            "length_chars": len(row["text"]),
            "length_bucket": "curto" if len(row["text"]) < 60 else "medio" if len(row["text"]) < 200 else "longo",
        },
    }


def lint(splits: dict[str, list[dict]]) -> list[str]:
    errors, seen_ids, group_split = [], set(), {}
    for name, rows in splits.items():
        for r in rows:
            if r["id"] in seen_ids:
                errors.append(f"id duplicado {r['id']}")
            seen_ids.add(r["id"])
            if not 2 <= len(r["options"]) <= MAX_OPTIONS:
                errors.append(f"{r['id']}: {len(r['options'])} opções")
            if r["gold_label"] not in r["options"]:
                errors.append(f"{r['id']}: rótulo fora das opções")
            if list(r["options"])[-1] != FALLBACK:
                errors.append(f"{r['id']}: fallback não é a última opção")
            if group_split.setdefault(r["group_id"], name) != name:
                errors.append(f"grupo {r['group_id']} em mais de uma partição")
    return errors


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--freeze", action="store_true")
    args = ap.parse_args()
    run = Path(args.run)
    rows = [json.loads(l) for l in (run / "annotated.jsonl").open()]
    split_of = assign_splits(rows)
    splits = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["id"]):
        splits[split_of[r["group_id"]]].append(to_example(r, split_of[r["group_id"]]))
    errors = lint(splits)
    if errors:
        raise SystemExit("lint reprovado:\n" + "\n".join(errors[:20]))
    SPLITS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"version": "d1-v1", "taxonomy_version": taxonomy.load()["version"],
                "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_run": str(run), "seed": SEED, "splits": {}}
    for name in ("dev", "calibration", "test"):
        path = SPLITS_DIR / f"{name}.jsonl"
        with path.open("w") as f:
            for ex in splits[name]:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
        rows_ = splits[name]
        manifest["splits"][name] = {
            "file": path.name, "sha256": sha256_file(path), "examples": len(rows_),
            "groups": len({r["group_id"] for r in rows_}),
            "labels": len({r["gold_label"] for r in rows_}),
            "oos": sum(r["metadata"]["kind"] == "oos" for r in rows_),
            "gold_not_eligible": sum(not r["metadata"]["gold_eligible"] for r in rows_),
            "n_options": dict(sorted(Counter(r["metadata"]["n_options"] for r in rows_).items())),
        }
    (SPLITS_DIR / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(manifest["splits"], indent=1))
    if args.freeze:
        from harness import objstore
        stamp = manifest["built_at"].replace(":", "").replace("-", "")
        for bucket in ("dmb-entrada", "dmb-logs-imutaveis"):
            for f in ["MANIFEST.json"] + [f"{n}.jsonl" for n in ("dev", "calibration", "test")]:
                objstore.put(bucket, f"splits/{manifest['version']}/{stamp}/{f}", SPLITS_DIR / f)
            for f in ("generated.jsonl", "candidates.jsonl", "annotations.jsonl", "annotated.jsonl",
                      "prepare-report.json", "annotation-report.json"):
                if (run / f).exists():
                    objstore.put(bucket, f"datagen/{manifest['version']}/{stamp}/{f}", run / f)
        print(f"congelado em dmb-entrada e dmb-logs-imutaveis: splits/{manifest['version']}/{stamp}/")


if __name__ == "__main__":
    main()
