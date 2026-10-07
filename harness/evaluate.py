"""Executa um candidato sobre uma partição congelada (tarefas 52–57, 59, 63).

- Confere o SHA-256 da partição contra data/splits/MANIFEST.json.
- Amostra determinística (seed) quando --limit é usado; ordem fixa por id.
- Mesma política de truncamento para todos (dmb.canonical.fit_state) e contagem de tokens por entrada.
- Lote 1, sem paralelismo; os primeiros --warmup exemplos ficam marcados e fora das estatísticas de latência.
- Mede tempo de carga, latência por decisão, pico de RAM (VmHWM) e de memória/uso de GPU (nvidia-smi).
- A partição de teste só roda com a configuração congelada (config/frozen.json, tarefa 62).

Uso: python -m harness.evaluate --candidate laya --models-root ... --device cpu --out DIR
Parâmetros também por ambiente: DMB_SPLIT (dev), DMB_LIMIT (todos), DMB_SEED, DMB_WARMUP, DMB_STATE_BUDGET.
"""
import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

from dmb.offline import enforce_offline

ROOT = Path(__file__).resolve().parents[1]
SPLITS = ROOT / "data" / "splits"
FROZEN = ROOT / "config" / "frozen.json"


class GpuSampler(threading.Thread):
    """Amostra memória usada e utilização da GPU a cada 0,5 s (nvidia-smi)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.samples, self.stop_flag = [], threading.Event()

    def run(self):
        while not self.stop_flag.is_set():
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                                      "--format=csv,noheader,nounits"], capture_output=True, text=True,
                                     timeout=5).stdout.strip().splitlines()[0]
                mem, util = (float(x) for x in out.split(","))
                self.samples.append((mem, util))
            except Exception:
                return
            self.stop_flag.wait(0.5)

    def summary(self) -> dict:
        if not self.samples:
            return {}
        return {"gpu_mem_peak_mib": max(m for m, _ in self.samples),
                "gpu_util_mean_pct": sum(u for _, u in self.samples) / len(self.samples)}


def rss_peak_mib() -> float | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
    except OSError:
        return None
    return None


def load_split(name: str) -> list[dict]:
    manifest = json.loads((SPLITS / "MANIFEST.json").read_text())
    info = manifest["splits"][name]
    path = SPLITS / info["file"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != info["sha256"]:
        raise SystemExit(f"partição {name} diverge do MANIFEST (SHA-256)")
    return [json.loads(l) for l in path.open()]


def model_precision(adapter) -> str | None:
    for attr in ("model", "agent"):
        obj = getattr(adapter, attr, None)
        for cand in (obj, getattr(obj, "model", None)):
            if cand is not None and hasattr(cand, "parameters"):
                try:
                    return str(next(cand.parameters()).dtype).replace("torch.", "")
                except StopIteration:
                    pass
    return "gguf-q8_0" if adapter.name == "rizzo_flow" else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--models-root", default="models")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--out", required=True)
    ap.add_argument("--split", default=os.environ.get("DMB_SPLIT", "dev"))
    ap.add_argument("--limit", type=int, default=int(os.environ.get("DMB_LIMIT", "0")) or None)
    ap.add_argument("--seed", type=int, default=int(os.environ.get("DMB_SEED", "20261007")))
    ap.add_argument("--warmup", type=int, default=int(os.environ.get("DMB_WARMUP", "5")))
    ap.add_argument("--state-budget", type=int, default=int(os.environ.get("DMB_STATE_BUDGET", "512")))
    args = ap.parse_args()

    if args.split == "test" and not FROZEN.is_file():
        raise SystemExit("partição de teste bloqueada: configuração ainda não congelada (tarefa 62)")

    enforce_offline()
    from dmb.offline import self_test
    guard = self_test()
    if not guard["process_guard"].startswith("ok"):
        raise SystemExit(f"bloqueio de rede inativo: {guard}")

    from analysis.metrics import calibration, classification, latency_summary
    from dmb.canonical import to_jev_request
    from dmb.jev import JevError
    from dmb.server import systemone
    from harness.candidates import build_adapter

    examples = sorted(load_split(args.split), key=lambda e: e["id"])
    if args.limit:
        examples = sorted(random.Random(args.seed).sample(examples, min(args.limit, len(examples))),
                          key=lambda e: e["id"])
        random.Random(args.seed).shuffle(examples)  # ordem fixa, mas sem agrupar por intenção

    gpu = GpuSampler()
    gpu.start()
    adapter = build_adapter(args.candidate, args.models_root, args.device)
    t0 = time.perf_counter()
    adapter.load()
    load_s = time.perf_counter() - t0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with (out / f"predictions-{args.candidate}-{args.device}-{args.split}.jsonl").open("w") as f:
        for i, ex in enumerate(examples):
            request, info = to_jev_request(ex, adapter.model_id, n_turns=0, budget=args.state_budget,
                                           count_tokens=adapter.count_tokens)
            row = {"id": ex["id"], "gold": ex["gold_label"], "warmup": i < args.warmup,
                   "state_tokens": info.get("tokens"), "truncated": info.get("truncated", False),
                   "n_options": len(ex["options"]), "meta": ex["metadata"]}
            started = time.perf_counter()
            try:
                resp = systemone(adapter, request)
                ans = resp["answers"][ex["task"]]
                row.update(pred=ans["choice"], probabilities=ans["probabilities"],
                           confidence=ans.get("confidence"), input_tokens=resp["usage"]["input_tokens"],
                           latency_ms=resp["metadata"]["latency_ms"])
            except JevError as error:
                row.update(pred=None, error=error.error_type, error_message=error.message[:200],
                           latency_ms=(time.perf_counter() - started) * 1000)
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if (i + 1) % 50 == 0:
                print(f"{i + 1}/{len(examples)}", flush=True)
    gpu.stop_flag.set()

    measured = [r for r in rows if not r["warmup"]]
    summary = {
        "candidate": adapter.describe(), "precision": model_precision(adapter), "device": args.device,
        "split": args.split, "examples": len(rows), "seed": args.seed, "warmup": args.warmup,
        "batch_size": 1, "state_budget_tokens": args.state_budget, **guard,
        "load_seconds": round(load_s, 2),
        "warmup_latency_ms": [round(r["latency_ms"], 1) for r in rows if r["warmup"]],
        "latency_ms": latency_summary([r["latency_ms"] for r in measured if r.get("pred") is not None]),
        "errors": {k: sum(r.get("error") == k for r in rows) for k in {r.get("error") for r in rows} if k},
        "truncated": sum(r["truncated"] for r in rows),
        "state_tokens_max": max((r["state_tokens"] or 0) for r in rows),
        "rss_peak_mib": rss_peak_mib(), **gpu.summary(),
        "quality": {k: v for k, v in classification(rows).items() if k != "per_label"},
        "calibration_raw": calibration([r for r in rows if r.get("pred")]),
    }
    (out / f"summary-{args.candidate}-{args.device}-{args.split}.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: summary[k] for k in ("examples", "load_seconds", "latency_ms", "errors", "quality")},
                     ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
