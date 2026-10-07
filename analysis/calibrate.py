"""Calibração e limiares de abstenção, só com a partição de calibração (tarefas 60–61; Q5, Q10).

Para cada candidato × dispositivo:
- temperature scaling sobre log-probabilidades (um parâmetro T, minimizando NLL);
- o T só é aceito se reduzir o ECE em validação cruzada de 5 dobras por `group_id`; senão T = 1;
- limiar de abstenção sobre max(p) calibrado: a maior cobertura com taxa de rota errada com
  confiança alta ≤ 2% (Q5). Abster-se = encaminhar para desambiguação.

Uso: python -m analysis.calibrate reports/calibration  →  config/calibration.json
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from analysis.metrics import calibration, selective

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "calibration.json"
MAX_CONFIDENT_WRONG = 0.02
MIN_COVERAGE = 0.80
GRID = [math.exp(x / 40) for x in range(-160, 121)]  # T de ~0,018 a ~20


def group_of(example_id: str) -> str:
    return example_id.rsplit("-", 2)[0]  # "<group_id>-<nn>-D1"


def apply_temperature(probs: dict, t: float) -> dict:
    logits = {k: math.log(max(v, 1e-12)) / t for k, v in probs.items()}
    m = max(logits.values())
    exp = {k: math.exp(v - m) for k, v in logits.items()}
    z = sum(exp.values())
    return {k: v / z for k, v in exp.items()}


def calibrated_rows(rows: list[dict], t: float) -> list[dict]:
    out = []
    for r in rows:
        p = apply_temperature(r["probabilities"], t)
        out.append({**r, "probabilities": p, "pred": max(p, key=p.get)})
    return out


def nll(rows: list[dict], t: float) -> float:
    return -sum(math.log(max(apply_temperature(r["probabilities"], t)[r["gold"]], 1e-12)) for r in rows) / len(rows)


def fit_temperature(rows: list[dict]) -> float:
    return min(GRID, key=lambda t: nll(rows, t))


def cross_validated_ece(rows: list[dict], folds: int = 5) -> tuple[float, float]:
    groups = sorted({group_of(r["id"]) for r in rows})
    fold_of = {g: i % folds for i, g in enumerate(groups)}
    raw, cal = [], []
    for k in range(folds):
        train = [r for r in rows if fold_of[group_of(r["id"])] != k]
        test = [r for r in rows if fold_of[group_of(r["id"])] == k]
        if not test or not train:
            continue
        t = fit_temperature(train)
        raw.append(calibration(test)["ece"] * len(test))
        cal.append(calibration(calibrated_rows(test, t))["ece"] * len(test))
    n = len(rows)
    return sum(raw) / n, sum(cal) / n


def choose_threshold(rows: list[dict]) -> dict:
    confidences = sorted({round(max(r["probabilities"].values()), 6) for r in rows})
    best = selective(rows, 1.01)  # abstém de tudo: cobertura 0
    for thr in confidences:
        s = selective(rows, thr)
        if s["confident_wrong_rate"] <= MAX_CONFIDENT_WRONG:
            best = s
            break  # menor limiar que respeita o risco = maior cobertura
    return best


def main():
    src = Path(sys.argv[1])
    result = {"method": "temperature_scaling", "fit_split": "calibration",
              "max_confident_wrong_rate": MAX_CONFIDENT_WRONG, "min_coverage": MIN_COVERAGE, "candidates": {}}
    for f in sorted(src.glob("predictions-*.jsonl")):
        rows = [json.loads(l) for l in f.open()]
        rows = [r for r in rows if r.get("probabilities")]
        cand = json.loads((src / f.name.replace("predictions-", "summary-").replace(".jsonl", ".json"))
                          .read_text())["candidate"]["name"]
        device = f.stem.rsplit("-", 1)[1]
        t = fit_temperature(rows)
        ece_cv_raw, ece_cv_cal = cross_validated_ece(rows)
        accepted = ece_cv_cal < ece_cv_raw
        final_t = t if accepted else 1.0
        cal_rows = calibrated_rows(rows, final_t)
        thr = choose_threshold(cal_rows)
        result["candidates"].setdefault(cand, {})[device] = {
            "temperature": round(final_t, 4), "fitted_temperature": round(t, 4), "accepted": accepted,
            "n": len(rows), "ece_raw": round(calibration(rows)["ece"], 4),
            "ece_calibrated": round(calibration(cal_rows)["ece"], 4),
            "ece_cv_raw": round(ece_cv_raw, 4), "ece_cv_calibrated": round(ece_cv_cal, 4),
            "nll_raw": round(nll(rows, 1.0), 4), "nll_calibrated": round(nll(rows, final_t), 4),
            "threshold": round(thr["threshold"], 6), "coverage": round(thr["coverage"] or 0, 4),
            "selective_accuracy": round(thr["selective_accuracy"] or 0, 4),
            "confident_wrong_rate": round(thr["confident_wrong_rate"] or 0, 4),
            "meets_min_coverage": (thr["coverage"] or 0) >= MIN_COVERAGE,
        }
        print(cand, device, json.dumps(result["candidates"][cand][device]))
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print("→", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
