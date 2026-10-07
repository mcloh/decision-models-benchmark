"""Geração sintética dos enunciados (tarefas 24 e 27).

Cada lote = (intenção ou categoria fora de escopo) × perfil, com N enunciados distintos.
O lote é o `group_id`: enunciados do mesmo lote nunca são separados entre partições.
Geradores alternados (fornecedores distintos dos anotadores). Retomável: lotes já gravados
em <out>/generated.jsonl são pulados.

Uso (na VM): python -m datagen.generate --out /data/runs/datagen [--per-batch 12] [--workers 8]
"""
from __future__ import annotations

import argparse
import json
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dmb.llm import chat, extract_json
from datagen import taxonomy

GENERATORS = ["meta.llama-4-maverick-17b-128e-instruct-fp8", "cohere.command-a-03-2025"]
SEED = 20261007

PROFILES = {
    "curto_neutro": "mensagens curtas e diretas (3 a 12 palavras), tom neutro",
    "informal_abreviado": "linguagem informal de chat, com abreviações e gírias (vc, pq, q, tb, blz, mds, pfv)",
    "erros_digitacao": "MUITOS erros de digitação em toda mensagem: letras trocadas, faltando ou repetidas, sem acentuação, sem pontuação, tudo minúsculo, palavras grudadas",
    "regionalismo": "regionalismos e expressões de diferentes regiões do Brasil (Nordeste, Sul, Minas, Rio, São Paulo, Norte)",
    "emocional": "cliente irritado, frustrado, ansioso ou indignado; pode usar caixa alta, exclamações e xingamentos leves, mas com o pedido identificável",
    "longo_contexto": "mensagens longas (2 a 5 frases) contando a história do problema antes do pedido",
    "indireto_multiplo": "pedido indireto ou implícito; em metade das mensagens inclua também um segundo pedido secundário diferente",
}
OOS_PROFILES = ["curto_neutro", "informal_abreviado", "erros_digitacao", "regionalismo", "emocional",
                "longo_contexto", "indireto_multiplo", "curto_neutro", "emocional"]

SYSTEM = (
    "Você gera dados sintéticos realistas em português do Brasil para avaliar um classificador de "
    "intenções do atendimento digital de uma operadora de telefonia móvel. Escreva como clientes reais "
    "digitam no chat ou no aplicativo de mensagens. Nunca use nomes de empresas, marcas ou produtos reais, "
    "nem dados pessoais reais: se precisar de números, use valores claramente fictícios. "
    "Responda somente com JSON válido."
)


def batch_specs(per_batch: int) -> list[dict]:
    tax = taxonomy.load()
    specs = []
    for intent, info in tax["intents"].items():
        for profile in PROFILES:
            specs.append({"kind": "intent", "target": intent, "domain": info["domain"], "profile": profile})
    for oos in tax["out_of_scope"]:
        for i, profile in enumerate(OOS_PROFILES):
            specs.append({"kind": "oos", "target": oos, "domain": "fora_de_escopo", "profile": profile, "rep": i})
    for i, s in enumerate(specs):
        s["group_id"] = f"g{i:04d}-{s['target']}-{s['profile']}" + (f"-{s['rep']}" if "rep" in s else "")
        s["generator"] = GENERATORS[i % len(GENERATORS)]
        s["n"] = per_batch
    return specs


def prompt(spec: dict) -> str:
    tax = taxonomy.load()
    if spec["kind"] == "intent":
        info = tax["intents"][spec["target"]]
        others = [k for k in tax["intents"] if k != spec["target"]]
        rng = random.Random(f"{SEED}-{spec['group_id']}")
        hints = info["confusable_with"] + rng.sample(others, 3)
        target = (f"Intenção que TODAS as mensagens devem expressar como pedido principal: "
                  f"`{spec['target']}` — {info['description']}.\n"
                  f"Cuidado para não escrever mensagens que se encaixem melhor nestas outras intenções: "
                  + "; ".join(f"`{h}` ({tax['intents'][h]['description']})" for h in hints) + ".")
        if spec["profile"] == "indireto_multiplo":
            secondary = ("Em metade das mensagens inclua um segundo pedido, de intenção diferente da principal, "
                         "e informe o id em `secundaria` escolhendo entre: " + ", ".join(sorted(tax["intents"]))
                         + ". Nas demais, `secundaria`: null.")
        else:
            secondary = "Cada mensagem deve conter UM ÚNICO pedido, sem pedidos adicionais; `secundaria`: null."
    else:
        target = (f"As mensagens NÃO devem ter nenhum pedido de atendimento de telefonia. Categoria: "
                  f"`{spec['target']}` — {tax['out_of_scope'][spec['target']]}.")
        secondary = "Use `secundaria`: null."
    return (
        f"{target}\n\nEstilo do lote: {PROFILES[spec['profile']]}.\n\n"
        f"Gere {spec['n']} mensagens diferentes entre si (vocabulário, estrutura e situação variados; "
        f"não repita o mesmo início). {secondary}\n\n"
        "Formato: lista JSON de objetos com as chaves `texto` (a mensagem), `sentimento` "
        "(neutro, positivo, frustrado, irritado, ansioso ou indignado) e `secundaria` (id ou null)."
    )


def run_batch(spec: dict) -> list[dict]:
    raw = chat(spec["generator"], SYSTEM, prompt(spec), temperature=0.9, max_tokens=4000)
    items = extract_json(raw)
    rows = []
    for j, it in enumerate(items[: spec["n"]]):
        text = (it.get("texto") or "").strip()
        if not text:
            continue
        rows.append({
            "id": f"{spec['group_id']}-{j:02d}", "group_id": spec["group_id"], "text": text,
            "gen_label": spec["target"] if spec["kind"] == "intent" else "sem_correspondencia",
            "gen_target": spec["target"], "kind": spec["kind"], "domain": spec["domain"],
            "profile": spec["profile"], "sentiment": it.get("sentimento"),
            "gen_secondary": it.get("secundaria"), "generator": spec["generator"],
            "taxonomy_version": taxonomy.load()["version"],
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-batch", type=int, default=12)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "generated.jsonl"
    done = set()
    if path.exists():
        done = {json.loads(l)["group_id"] for l in path.open()}
    specs = [s for s in batch_specs(args.per_batch) if s["group_id"] not in done][: args.limit]
    print(f"{len(specs)} lotes a gerar ({len(done)} já prontos)", flush=True)
    lock = threading.Lock()
    failures = []
    with ThreadPoolExecutor(args.workers) as pool, path.open("a") as f:
        futures = {pool.submit(run_batch, s): s for s in specs}
        for i, fut in enumerate(as_completed(futures), 1):
            spec = futures[fut]
            try:
                rows = fut.result()
            except Exception as error:  # um lote ruim não derruba a geração; é refeito na próxima rodada
                failures.append((spec["group_id"], str(error)[:120]))
                continue
            with lock:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
            if i % 20 == 0:
                print(f"{i}/{len(specs)} lotes", flush=True)
    print(f"falhas: {len(failures)}", *failures[:10], sep="\n", flush=True)


if __name__ == "__main__":
    main()
