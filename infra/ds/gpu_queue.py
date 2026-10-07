"""Fila de jobs de GPU (o limite em sa-saopaulo-1 é de uma A10 por vez).

Uso: PYTHONPATH=infra/oci:infra/ds .venv/bin/python infra/ds/gpu_queue.py <modo> <candidato> [...] \
        [--after <job_run_ocid>] [--shape VM.GPU.A10.1]
Grava "candidato run_ocid estado" em runs/gpu-queue.log.
"""
import argparse
import time
from pathlib import Path

import jobs
import provision

LOG = Path(__file__).resolve().parents[2] / "runs" / "gpu-queue.log"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode")
    ap.add_argument("candidates", nargs="+")
    ap.add_argument("--after")
    ap.add_argument("--shape", default="VM.GPU.A10.1")
    ap.add_argument("--storage", type=int, default=100)
    ap.add_argument("--env", nargs="*", default=[], help="variáveis extras K=V (ex.: DMB_SPLIT=dev DMB_LIMIT=50)")
    args = ap.parse_args()
    LOG.parent.mkdir(exist_ok=True)
    if args.after:
        jobs.wait(args.after, poll=30)
    for cand in args.candidates:
        while True:
            try:
                run_id = jobs.run_job(f"{args.mode}-{cand}-gpu", "infra/ds/run_job.sh", args.shape, None, None,
                                      False, {"DMB_CANDIDATE": cand, "DMB_MODE": args.mode, "DMB_DEVICE": "auto",
                                       **dict(kv.split("=", 1) for kv in args.env)},
                                      storage_gb=args.storage, region=provision.GPU_REGION)
                break
            except jobs.oci.exceptions.ServiceError as error:
                if error.code != "LimitExceeded":
                    raise
                time.sleep(60)  # outra GPU ainda ocupada
        r = jobs.wait(run_id, poll=30)
        line = f"{cand} {run_id} {r.lifecycle_state} {(r.lifecycle_details or '')[:80]}"
        print(line, flush=True)
        with LOG.open("a") as f:
            f.write(line + "\n")


if __name__ == "__main__":
    main()
