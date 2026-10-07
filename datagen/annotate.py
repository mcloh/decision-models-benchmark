"""Anotação por três modelos generativos em rodízio (tarefas 30–32).

Para o lote b (10 mensagens embaralhadas): anotadores A = M[b % 3] e B = M[(b+1) % 3], de forma
independente e sem ver o rótulo de geração; desempate T = M[(b+2) % 3] só quando A ≠ B. T vê as duas
propostas (anônimas) e decide; se escolher um terceiro rótulo, o exemplo é excluído (ambiguidade alta).

Uso: python -m datagen.annotate --run /data/runs/datagen-v1 [--workers 6]
Entrada: candidates.jsonl. Saída: annotations.jsonl (bruto, retomável), annotated.jsonl, annotation-report.json.
"""
from __future__ import annotations

import argparse
import json
import random
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path

from dmb.llm import chat, extract_json
from datagen import taxonomy

ANNOTATORS = ["openai.gpt-5.5", "google.gemini-2.5-pro", "xai.grok-4.3"]
BATCH = 10
SEED = 20261007
AMBIGUITY = {"baixa", "media", "alta"}


def system_prompt() -> str:
    return (taxonomy.guide() + "\n\n## Taxonomia\n\n" + taxonomy.taxonomy_block()
            + "\n\nResponda somente com JSON válido.")


def annotate_batch(model: str, items: list[dict]) -> dict[str, dict]:
    payload = [{"id": it["id"], "mensagem": it["text"]} for it in items]
    user = ("Anote cada mensagem. Devolva uma lista JSON com um objeto por mensagem, com as chaves "
            "`id`, `rotulo`, `secundarias`, `ambiguidade` e `justificativa`.\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=1))
    valid = taxonomy.labels()
    out = {}
    for attempt in range(2):
        pending = [it for it in items if it["id"] not in out]
        if not pending:
            break
        if attempt:
            user = user.split("\n\n")[0] + "\n\n" + json.dumps(
                [{"id": it["id"], "mensagem": it["text"]} for it in pending], ensure_ascii=False, indent=1)
        try:
            answer = extract_json(chat(model, system_prompt(), user, temperature=0.0, max_tokens=12000))
        except Exception:
            continue
        for a in answer if isinstance(answer, list) else []:
            if not isinstance(a, dict) or a.get("rotulo") not in valid:
                continue
            out[str(a.get("id"))] = {
                "rotulo": a["rotulo"],
                "secundarias": [s for s in (a.get("secundarias") or []) if s in valid and s != a["rotulo"]],
                "ambiguidade": a.get("ambiguidade") if a.get("ambiguidade") in AMBIGUITY else None,
                "justificativa": str(a.get("justificativa") or "")[:300],
            }
    return out


def adjudicate(model: str, item: dict, a: dict, b: dict) -> dict | None:
    user = (
        "Duas anotações independentes discordaram. Decida o rótulo correto segundo o guia; você pode "
        "escolher uma das duas propostas ou outro rótulo da taxonomia.\n\n"
        f"Mensagem: {item['text']}\n\n"
        f"Proposta 1: `{a['rotulo']}` — {a['justificativa']}\n"
        f"Proposta 2: `{b['rotulo']}` — {b['justificativa']}\n\n"
        "Devolva um objeto JSON com `rotulo`, `ambiguidade` e `justificativa`."
    )
    try:
        ans = extract_json(chat(model, system_prompt(), user, temperature=0.0, max_tokens=4000))
    except Exception:
        return None
    if not isinstance(ans, dict) or ans.get("rotulo") not in taxonomy.labels():
        return None
    return {"rotulo": ans["rotulo"], "ambiguidade": ans.get("ambiguidade"),
            "justificativa": str(ans.get("justificativa") or "")[:300]}


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    if not pairs:
        return None
    n = len(pairs)
    po = sum(x == y for x, y in pairs) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum(ca[k] * cb.get(k, 0) for k in ca) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    run = Path(args.run)
    items = [json.loads(l) for l in (run / "candidates.jsonl").open()]
    random.Random(SEED).shuffle(items)
    items = items[: args.limit]
    by_id = {it["id"]: it for it in items}
    batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]

    raw_path = run / "annotations.jsonl"
    raw = defaultdict(dict)  # id -> role -> registro
    if raw_path.exists():
        for l in raw_path.open():
            r = json.loads(l)
            raw[r["id"]][r["role"]] = r
    lock = threading.Lock()
    f = raw_path.open("a")

    def save(rec):
        with lock:
            raw[rec["id"]][rec["role"]] = rec
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()

    def roles(b):
        return {"A": ANNOTATORS[b % 3], "B": ANNOTATORS[(b + 1) % 3], "T": ANNOTATORS[(b + 2) % 3]}

    def do_batch(b):
        rl = roles(b)
        for role in ("A", "B"):
            todo = [it for it in batches[b] if role not in raw[it["id"]]]
            if todo:
                for id_, ann in annotate_batch(rl[role], todo).items():
                    if id_ in by_id:
                        save({"id": id_, "role": role, "model": rl[role], **ann})
        for it in batches[b]:
            r = raw[it["id"]]
            if "A" in r and "B" in r and r["A"]["rotulo"] != r["B"]["rotulo"] and "T" not in r:
                dec = adjudicate(rl["T"], it, r["A"], r["B"])
                if dec:
                    save({"id": it["id"], "role": "T", "model": rl["T"], **dec})
        return b

    with ThreadPoolExecutor(args.workers) as pool:
        for i, _ in enumerate(pool.map(do_batch, range(len(batches))), 1):
            if i % 25 == 0:
                print(f"{i}/{len(batches)} lotes anotados", flush=True)
    f.close()

    # Consolidação
    final, status = [], Counter()
    pairs = defaultdict(list)
    for it in items:
        r = raw[it["id"]]
        if "A" not in r or "B" not in r:
            status["excluido_falha_anotacao"] += 1
            continue
        a, b = r["A"], r["B"]
        pairs[tuple(sorted((a["model"], b["model"])))].append(
            (a["rotulo"], b["rotulo"]) if a["model"] < b["model"] else (b["rotulo"], a["rotulo"]))
        if a["rotulo"] == b["rotulo"]:
            gold, how, why = a["rotulo"], "consenso", a["justificativa"]
        elif "T" in r and r["T"]["rotulo"] in (a["rotulo"], b["rotulo"]):
            gold, how, why = r["T"]["rotulo"], "desempate", r["T"]["justificativa"]
        else:
            status["excluido_tres_rotulos" if "T" in r else "excluido_sem_desempate"] += 1
            continue
        status[how] += 1
        amb = [x.get("ambiguidade") for x in (a, b, r.get("T") or {}) if x.get("ambiguidade")]
        final.append({**it, "gold_label": gold, "annotation": how, "justification": why,
                      "annotators": {k: {"model": v["model"], "rotulo": v["rotulo"]} for k, v in r.items()},
                      "ambiguity": max(amb, key=["baixa", "media", "alta"].index) if amb else None,
                      "secondary": sorted(set(a.get("secundarias", [])) | set(b.get("secundarias", []))),
                      "gen_agreement": gold == it["gen_label"]})
    with (run / "annotated.jsonl").open("w") as out:
        for r in final:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
    report = {
        "annotators": ANNOTATORS, "items": len(items), "status": dict(status),
        "cohen_kappa": {f"{x} × {y}": round(cohen_kappa(p), 4) for (x, y), p in pairs.items()},
        "raw_agreement": round(sum(s for s in [status["consenso"]]) / max(1, len(items)), 4),
        "agreement_with_generation": round(sum(r["gen_agreement"] for r in final) / max(1, len(final)), 4),
        "gold_distribution": dict(Counter(r["gold_label"] for r in final).most_common()),
    }
    (run / "annotation-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: report[k] for k in ("items", "status", "cohen_kappa", "raw_agreement",
                                             "agreement_with_generation")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
