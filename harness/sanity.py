"""Conformidade e sanidade de um candidato real (tarefas 41, 49–51).

Executa as fixtures de conformidade e os casos de sanidade (decisões triviais, os três
tipos de pergunta e a mesma pergunta com as opções em ordem invertida) e grava um
relatório JSON. Falha (código 1) só por violação de contrato; os acertos de sanidade
são reportados, não exigidos.

Uso: python -m harness.sanity --candidate laya --models-root models --device cpu --out reports/sanity
"""
import argparse
import json
import sys
import time
from pathlib import Path

from dmb.offline import enforce_offline

FIXTURES = Path(__file__).resolve().parents[1] / "contracts" / "jev" / "fixtures"


def predicted(answer: dict) -> str:
    if answer["type"] == "noul":
        return "true" if answer["noul"] >= 0.5 else "false"
    return max(answer["probabilities"], key=answer["probabilities"].get)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--models-root", default="models")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--out", default="reports/sanity")
    args = ap.parse_args()

    enforce_offline()
    from dmb.offline import self_test
    guard = self_test()
    if not guard["process_guard"].startswith("ok"):
        sys.exit(f"bloqueio de rede inativo: {guard}")
    from dmb.jev import JevError
    from dmb.server import systemone
    from harness.candidates import build_adapter

    adapter = build_adapter(args.candidate, args.models_root, args.device)
    started = time.perf_counter()
    adapter.load()
    load_s = time.perf_counter() - started

    violations, conformance = [], []
    for case in json.loads((FIXTURES / "conformance.json").read_text())["cases"]:
        try:
            systemone(adapter, case["request"])
            outcome = "ok"
        except JevError as error:
            outcome = error.error_type
        conformance.append({"name": case["name"], "expected": case["expect"], "got": outcome})
        if outcome != case["expect"]:
            violations.append(f"conformance:{case['name']}: esperado {case['expect']}, obtido {outcome}")

    sanity = []
    for case in json.loads((FIXTURES / "sanity.json").read_text())["cases"]:
        q = case["question"]
        request = {"model": adapter.model_id, "state": case["state"], "questions": {"q": q}}
        r = systemone(adapter, request)
        row = {"name": case["name"], "gold": case["gold"], "pred": predicted(r["answers"]["q"]),
               "latency_ms": round(r["metadata"]["latency_ms"], 1), "answer": r["answers"]["q"]}
        if q["type"] == "choice":
            flipped = dict(reversed(list(q["criteria"].items())))
            r2 = systemone(adapter, {**request, "questions": {"q": {**q, "criteria": flipped}}})
            if list(r2["answers"]["q"]["probabilities"]) != list(flipped):
                violations.append(f"sanity:{case['name']}: ordem das opções não preservada")
            row["pred_permuted"] = predicted(r2["answers"]["q"])
            row["permutation_invariant"] = row["pred_permuted"] == row["pred"]
        row["correct"] = row["pred"] == row["gold"]
        sanity.append(row)

    report = {
        "candidate": adapter.describe(), "device": args.device,
        "load_seconds": round(load_s, 2), **guard,
        "conformance": conformance, "sanity": sanity,
        "summary": {
            "contract_violations": violations,
            "sanity_correct": f"{sum(r['correct'] for r in sanity)}/{len(sanity)}",
            "permutation_invariant": f"{sum(r.get('permutation_invariant', False) for r in sanity)}"
                                     f"/{sum('permutation_invariant' in r for r in sanity)}",
        },
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{args.candidate}-{args.device}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False), "load_s=", report["load_seconds"])
    print("relatório:", path)
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
