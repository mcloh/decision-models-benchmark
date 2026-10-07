"""Resumo das execuções gravadas em dmb-resultados/runs/.

Uso: PYTHONPATH=infra/oci .venv/bin/python infra/ds/results.py [filtro]
"""
import json
import sys

import oci

from session import load_config

BUCKET = "dmb-resultados"


def main():
    needle = sys.argv[1] if len(sys.argv) > 1 else ""
    c = oci.object_storage.ObjectStorageClient(load_config())
    ns = c.get_namespace().data
    names = [o.name for o in oci.pagination.list_call_get_all_results(
        c.list_objects, ns, BUCKET, prefix="runs/").data.objects]
    for name in sorted(n for n in names if n.endswith("/run.json") and needle in n):
        run = json.loads(c.get_object(ns, BUCKET, name).data.content)
        line = {k: run.get(k) for k in ("run_id", "candidate", "device", "status")}
        line["gate"] = run.get("egress_gate", {}).get("passed")
        prefix = name.rsplit("/", 1)[0]
        for n in names:
            if n.startswith(prefix) and n.endswith(".json") and n != name:
                rep = json.loads(c.get_object(ns, BUCKET, n).data.content)
                if "summary" in rep:
                    line |= rep["summary"] | {"load_s": rep.get("load_seconds")}
                    lat = [r["latency_ms"] for r in rep.get("sanity", [])]
                    if lat:
                        line["latency_ms_median"] = sorted(lat)[len(lat) // 2]
        print(json.dumps(line, ensure_ascii=False))


if __name__ == "__main__":
    main()
