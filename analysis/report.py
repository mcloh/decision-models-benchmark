"""Análise do teste final (tarefas 67–74) a partir de reports/test/ (coletado com --all-reps).

Qualidade e calibração usam a repetição 1 (as predições são determinísticas por candidato e
dispositivo; a concordância entre repetições é reportada). Desempenho usa as 3 repetições.

Uso: python -m analysis.report reports/test  →  reports/test/analysis.json (+ confusion-*.csv, errors-*.jsonl)
"""
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from analysis.calibrate import apply_temperature, group_of
from analysis.metrics import calibration, classification, selective

ROOT = Path(__file__).resolve().parents[1]
FALLBACK = "sem_correspondencia"
BOOT = 2000
SEED = 20261007
SLICES = ["profile", "n_options", "kind", "gold_eligible", "length_bucket", "sentiment", "domain", "annotation"]


def load_runs(src: Path) -> dict:
    runs = defaultdict(dict)  # (cand, dev) -> rep -> {"summary", "rows"}
    for f in sorted(src.glob("summary-*-r*.json")):
        s = json.loads(f.read_text())
        rep = int(f.stem.rsplit("-r", 1)[1])
        preds = f.with_name(f.name.replace("summary-", "predictions-").replace(".json", ".jsonl"))
        rows = [json.loads(l) for l in preds.open()] if preds.exists() else []
        runs[(s["candidate"]["name"], s["device"])][rep] = {"summary": s, "rows": rows}
    return runs


def calibrated(rows, t):
    out = []
    for r in rows:
        if r.get("probabilities"):
            p = apply_temperature(r["probabilities"], t)
            out.append({**r, "probabilities": p, "pred": max(p, key=p.get)})
        else:
            out.append(r)
    return out


def cluster_bootstrap(rows, stat, n=BOOT, seed=SEED):
    groups = defaultdict(list)
    for r in rows:
        groups[group_of(r["id"])].append(r)
    keys = sorted(groups)
    rng = random.Random(seed)
    values = []
    for _ in range(n):
        sample = [r for k in rng.choices(keys, k=len(keys)) for r in groups[k]]
        values.append(stat(sample))
    values.sort()
    return values[int(0.025 * n)], values[int(0.975 * n) - 1]


def accuracy(rows):
    ok = [r for r in rows if r.get("pred") is not None]
    return sum(r["pred"] == r["gold"] for r in ok) / len(ok) if ok else 0.0


def mcnemar(a_rows, b_rows):
    """Teste exato de McNemar (binomial bilateral) sobre os pares discordantes."""
    b_by_id = {r["id"]: r for r in b_rows}
    n01 = n10 = 0
    for r in a_rows:
        o = b_by_id.get(r["id"])
        if not o:
            continue
        a_ok, b_ok = r["pred"] == r["gold"], o["pred"] == o["gold"]
        n10 += a_ok and not b_ok
        n01 += b_ok and not a_ok
    n, k = n01 + n10, min(n01, n10)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n) if n else 1.0
    return {"a_only": n10, "b_only": n01, "p_value": p}


def paired_diff_ci(a_rows, b_rows):
    b_by_id = {r["id"]: r for r in b_rows}
    pairs = [(r, b_by_id[r["id"]]) for r in a_rows if r["id"] in b_by_id]
    def diff(sample):
        return sum((a["pred"] == a["gold"]) - (b["pred"] == b["gold"]) for a, b in sample) / len(sample)
    groups = defaultdict(list)
    for a, b in pairs:
        groups[group_of(a["id"])].append((a, b))
    keys = sorted(groups)
    rng = random.Random(SEED)
    vals = sorted(diff([p for k in rng.choices(keys, k=len(keys)) for p in groups[k]]) for _ in range(BOOT))
    return diff(pairs), vals[int(0.025 * BOOT)], vals[int(0.975 * BOOT) - 1]


def error_class(r, taxonomy) -> str:
    """Classificação automática dos erros (tarefa 73)."""
    m = r["meta"]
    gold, pred = r["gold"], r["pred"]
    if r.get("truncated"):
        return "truncamento"
    if gold != FALLBACK and pred == FALLBACK:
        return "abstencao_indevida"
    if gold == FALLBACK and m.get("kind") == "oos":
        return "fora_de_escopo_aceito"
    if gold == FALLBACK and not m.get("gold_eligible", True):
        return "intencao_fora_das_opcoes"
    if pred in taxonomy.get(gold, {}).get("confusable_with", []) or gold in taxonomy.get(pred, {}).get("confusable_with", []):
        return "taxonomia_par_dificil"
    if m.get("ambiguity") in ("media", "alta") or m.get("annotation") == "desempate" or m.get("secondary"):
        return "ambiguidade"
    if m.get("profile") in ("erros_digitacao", "regionalismo", "informal_abreviado"):
        return "linguagem"
    return "desempenho_do_modelo"


def mean_sd(values):
    values = [v for v in values if v is not None]
    if not values:
        return None, None
    mu = sum(values) / len(values)
    sd = (sum((v - mu) ** 2 for v in values) / (len(values) - 1)) ** 0.5 if len(values) > 1 else 0.0
    return mu, sd


def main():
    src = Path(sys.argv[1])
    cfg = yaml.safe_load((ROOT / "config" / "benchmark.yaml").read_text())
    cal = json.loads((ROOT / "config" / "calibration.json").read_text())["candidates"]
    prices = yaml.safe_load((ROOT / "config" / "pricing.yaml").read_text())["usd_per_hour"]
    manifest = json.loads((ROOT / "env" / "artifacts-manifest.json").read_text())
    frozen = json.loads((ROOT / "config" / "frozen.json").read_text())
    from datagen import taxonomy as tx
    taxonomy = tx.load()["intents"]
    runs = load_runs(src)
    out = {"split": "test", "criteria": cfg["criteria"], "candidates": {}}
    primary = {}

    for (cand, dev), reps in sorted(runs.items()):
        r1 = reps[min(reps)]
        raw = [r for r in r1["rows"] if not r.get("error")]
        params = cal.get(cand, {}).get(dev) or cal.get(cand, {}).get("cuda")
        cal_rows = calibrated(r1["rows"], params["temperature"])
        cls = classification(r1["rows"])
        lo, hi = cluster_bootstrap(r1["rows"], accuracy)
        sel = selective([r for r in cal_rows if r.get("probabilities")], params["threshold"])
        lat = {k: mean_sd([rep["summary"]["latency_ms"][k] for rep in reps.values()]) for k in ("p50", "p95", "p99", "mean")}
        agreement = None
        if len(reps) > 1:
            base = {r["id"]: r["pred"] for r in r1["rows"]}
            agreement = min(sum(base.get(r["id"]) == r["pred"] for r in rep["rows"]) / len(rep["rows"])
                            for rep in reps.values())
        mean_s = (lat["mean"][0] or 0) / 1000
        shape = "gpu_a10" if dev == "cuda" else "cpu_e4_8ocpu_64gb"
        price = prices.get(shape)
        art_bytes = sum(a["bytes"] for a in manifest["artifacts"] if a["candidate"] == cand and a["kind"] == "hf_model")
        conf = Counter((r["gold"], r["pred"]) for r in r1["rows"] if r.get("pred") and r["pred"] != r["gold"])
        errors = [r for r in r1["rows"] if r.get("pred") and r["pred"] != r["gold"]]
        err_classes = Counter(error_class(r, taxonomy) for r in errors)
        slices = {}
        for key in SLICES:
            buckets = defaultdict(list)
            for r in r1["rows"]:
                buckets[str(r["n_options"] if key == "n_options" else r["meta"].get(key))].append(r)
            slices[key] = {k: {"n": len(v), "accuracy": round(accuracy(v), 4)} for k, v in sorted(buckets.items())}
        entry = {
            "device": dev, "precision": r1["summary"].get("precision"), "repetitions": len(reps),
            "quality": {"n": cls["n"], "errors": cls.get("errors", 0), "accuracy": round(cls["accuracy"], 4),
                        "accuracy_ci95": [round(lo, 4), round(hi, 4)], "macro_f1": round(cls["macro_f1"], 4),
                        "macro_precision": round(cls["macro_precision"], 4), "macro_recall": round(cls["macro_recall"], 4),
                        "fallback_recall": round(cls["per_label"].get(FALLBACK, {}).get("recall", 0), 4),
                        "fallback_precision": round(cls["per_label"].get(FALLBACK, {}).get("precision", 0), 4)},
            "calibration": {"temperature": params["temperature"],
                            "raw": {k: round(v, 4) for k, v in calibration(raw).items()},
                            "calibrated": {k: round(v, 4) for k, v in calibration([r for r in cal_rows if r.get("probabilities")]).items()}},
            "abstention": {"threshold": params["threshold"], "coverage": round(sel["coverage"], 4),
                           "selective_accuracy": round(sel["selective_accuracy"] or 0, 4),
                           "confident_wrong_rate": round(sel["confident_wrong_rate"], 4)},
            "latency_ms": {k: {"mean": round(v[0], 2), "sd": round(v[1], 2)} for k, v in lat.items() if v[0] is not None},
            "throughput_decisions_per_s": round(1 / mean_s, 2) if mean_s else None,
            "cost_usd_per_1k_decisions": round(price * mean_s * 1000 / 3600, 4) if price and mean_s else None,
            "load_seconds": mean_sd([rep["summary"]["load_seconds"] for rep in reps.values()])[0],
            "rss_peak_mib": max(rep["summary"].get("rss_peak_mib") or 0 for rep in reps.values()),
            "gpu_mem_peak_mib": max(rep["summary"].get("gpu_mem_peak_mib") or 0 for rep in reps.values()) or None,
            "storage_mib": {"weights": round(art_bytes / 2 ** 20),
                            "environment": round(frozen["environments"].get(cand, {}).get("bytes", 0) / 2 ** 20)},
            "prediction_agreement_across_reps": agreement,
            "top_confusions": [{"gold": g, "pred": p, "n": n} for (g, p), n in conf.most_common(10)],
            "error_classes": dict(err_classes.most_common()),
            "slices": slices,
        }
        out["candidates"].setdefault(cand, {})[dev] = entry
        primary[(cand, dev)] = r1["rows"]
        with (src / f"confusion-{cand}-{dev}.csv").open("w") as f:
            f.write("gold,pred,n\n" + "".join(f"{g},{p},{n}\n" for (g, p), n in conf.most_common()))
        high_impact = sorted((r for r in cal_rows if r.get("pred") and r["pred"] != r["gold"]
                              and max(r["probabilities"].values()) >= params["threshold"]),
                             key=lambda r: -max(r["probabilities"].values()))
        with (src / f"errors-high-impact-{cand}-{dev}.jsonl").open("w") as f:
            for r in high_impact:
                f.write(json.dumps({"id": r["id"], "gold": r["gold"], "pred": r["pred"],
                                    "confidence": round(max(r["probabilities"].values()), 4),
                                    "class": error_class(r, taxonomy), "profile": r["meta"].get("profile")},
                                   ensure_ascii=False) + "\n")

    # Comparações pareadas em GPU contra o candidato de maior acurácia (tarefa 74)
    gpu = {c: rows for (c, d), rows in primary.items() if d == "cuda"}
    if gpu:
        best = max(gpu, key=lambda c: accuracy(gpu[c]))
        out["pairwise_vs_best_gpu"] = {"best": best, "comparisons": {}}
        for c, rows in gpu.items():
            if c == best:
                continue
            d, lo, hi = paired_diff_ci(gpu[best], rows)
            out["pairwise_vs_best_gpu"]["comparisons"][c] = {
                "accuracy_diff": round(d, 4), "ci95": [round(lo, 4), round(hi, 4)], **mcnemar(gpu[best], rows)}
    # Critérios pré-registrados (Q5)
    crit = cfg["criteria"]
    out["criteria_check"] = {}
    for cand, devs in out["candidates"].items():
        e = devs.get("cuda")
        if not e:
            continue
        out["criteria_check"][cand] = {
            "H3_latency_p95_gpu": e["latency_ms"]["p95"]["mean"] <= crit["latency_gpu_batch1"]["p95_ms_per_decision"],
            "H1_macro_f1_absolute": e["quality"]["macro_f1"] >= crit["accuracy"]["fallback_macro_f1_min"],
            "H2_risk": e["abstention"]["confident_wrong_rate"] <= crit["risk"]["max_confident_wrong_route_rate"]
                       and e["abstention"]["coverage"] >= crit["risk"]["min_coverage"],
        }
    (src / "analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    for cand, devs in out["candidates"].items():
        for dev, e in devs.items():
            q, a = e["quality"], e["abstention"]
            print(f"{cand:10} {dev:4} acc {q['accuracy']:.3f} {q['accuracy_ci95']} f1 {q['macro_f1']:.3f} "
                  f"cov {a['coverage']:.3f} cwr {a['confident_wrong_rate']:.3f} p95 {e['latency_ms']['p95']} "
                  f"agree {e['prediction_agreement_across_reps']}")
    print(json.dumps(out.get("pairwise_vs_best_gpu"), indent=1), json.dumps(out["criteria_check"], indent=1))


if __name__ == "__main__":
    main()
