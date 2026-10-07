"""Encontra um shape de GPU com capacidade: roda o job em cada shape, em ordem, até um não falhar
por falta de capacidade. Imprime o shape usado e o estado final.

Uso: PYTHONPATH=infra/oci:infra/ds .venv/bin/python infra/ds/gpu_probe.py <candidato> [shape ...]
"""
import sys

import jobs

DEFAULT_SHAPES = ["VM.GPU.A10.1", "VM.GPU.A10.2", "VM.GPU.A100.B40G.1", "VM.GPU.A100.80G.1", "VM.GPU3.1"]


def main():
    args = sys.argv[1:]
    region = None
    if args and args[0].startswith("--region="):
        region = args.pop(0).split("=", 1)[1]
    candidate, shapes = args[0], args[1:] or DEFAULT_SHAPES
    for shape in shapes:
        try:
            run_id = jobs.run_job(f"sanity-{candidate}-gpu", "infra/ds/run_job.sh", shape, None, None, region is None,
                                  {"DMB_CANDIDATE": candidate, "DMB_MODE": "sanity", "DMB_DEVICE": "auto"},
                                  storage_gb=60, region=region)
        except jobs.oci.exceptions.ServiceError as error:
            print(f"indisponível: {shape} ({error.code})", flush=True)
            continue
        r = jobs.wait(run_id, poll=20)
        if "no capacity" in (r.lifecycle_details or "").lower():
            print(f"sem capacidade: {shape}", flush=True)
            continue
        print(f"SHAPE {shape} -> {r.lifecycle_state} {run_id}", flush=True)
        return
    print("nenhum shape com capacidade", flush=True)


if __name__ == "__main__":
    main()
