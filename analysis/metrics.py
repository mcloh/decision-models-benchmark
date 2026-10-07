"""Métricas de qualidade e desempenho (tarefas 67–69)."""
from __future__ import annotations

import math
from collections import Counter, defaultdict

FALLBACK = "sem_correspondencia"


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def latency_summary(values: list[float]) -> dict:
    return {"n": len(values), "p50": percentile(values, 0.5), "p95": percentile(values, 0.95),
            "p99": percentile(values, 0.99), "mean": sum(values) / len(values) if values else None}


def classification(rows: list[dict]) -> dict:
    """rows: dicts com `gold`, `pred` (rótulos). Ignora linhas com erro (pred None)."""
    ok = [r for r in rows if r.get("pred") is not None]
    if not ok:
        return {"n": 0}
    labels = sorted({r["gold"] for r in ok} | {r["pred"] for r in ok})
    tp, fp, fn = Counter(), Counter(), Counter()
    for r in ok:
        if r["pred"] == r["gold"]:
            tp[r["gold"]] += 1
        else:
            fp[r["pred"]] += 1
            fn[r["gold"]] += 1
    per = {}
    for lab in labels:
        p = tp[lab] / (tp[lab] + fp[lab]) if tp[lab] + fp[lab] else 0.0
        rc = tp[lab] / (tp[lab] + fn[lab]) if tp[lab] + fn[lab] else 0.0
        per[lab] = {"precision": p, "recall": rc, "f1": 2 * p * rc / (p + rc) if p + rc else 0.0,
                    "support": tp[lab] + fn[lab]}
    gold_labels = [lab for lab in labels if per[lab]["support"] > 0]
    return {
        "n": len(ok), "errors": len(rows) - len(ok),
        "accuracy": sum(r["pred"] == r["gold"] for r in ok) / len(ok),
        "macro_f1": sum(per[lab]["f1"] for lab in gold_labels) / len(gold_labels),
        "macro_precision": sum(per[lab]["precision"] for lab in gold_labels) / len(gold_labels),
        "macro_recall": sum(per[lab]["recall"] for lab in gold_labels) / len(gold_labels),
        "per_label": per,
    }


def calibration(rows: list[dict], bins: int = 15) -> dict:
    """rows: `probabilities` (dict), `gold`, `pred`. Brier multiclasse e ECE sobre a confiança max(p)."""
    ok = [r for r in rows if r.get("probabilities")]
    if not ok:
        return {}
    brier = sum(sum((p - (k == r["gold"])) ** 2 for k, p in r["probabilities"].items()) for r in ok) / len(ok)
    nll = -sum(math.log(max(r["probabilities"].get(r["gold"], 0.0), 1e-12)) for r in ok) / len(ok)
    buckets = defaultdict(list)
    for r in ok:
        conf = max(r["probabilities"].values())
        buckets[min(int(conf * bins), bins - 1)].append((conf, r["pred"] == r["gold"]))
    ece = sum(len(b) / len(ok) * abs(sum(c for c, _ in b) / len(b) - sum(a for _, a in b) / len(b))
              for b in buckets.values())
    return {"brier": brier, "nll": nll, "ece": ece}


def selective(rows: list[dict], threshold: float) -> dict:
    """Abstém (encaminha para desambiguação) quando max(p) < limiar."""
    ok = [r for r in rows if r.get("probabilities")]
    kept = [r for r in ok if max(r["probabilities"].values()) >= threshold]
    wrong_confident = sum(r["pred"] != r["gold"] for r in kept)
    return {"threshold": threshold, "coverage": len(kept) / len(ok) if ok else None,
            "selective_accuracy": (len(kept) - wrong_confident) / len(kept) if kept else None,
            "confident_wrong_rate": wrong_confident / len(ok) if ok else None}
