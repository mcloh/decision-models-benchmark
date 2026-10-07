"""Réplica server-side dos artefatos para a região de GPU (copy_object entre regiões).

Copia os pesos (models/) e o ambiente atual de cada candidato (envs/<c>/latest.json e o
pacote que ele referencia). Objetos já presentes com o mesmo tamanho são pulados.

Uso: PYTHONPATH=infra/oci .venv/bin/python infra/oci/replicate.py [--wait]
"""
import json
import sys
import time

import oci

import provision
from session import load_config

SRC_BUCKET = "dmb-artefatos"
DST_BUCKET = f"dmb-artefatos{provision.GPU_SUFFIX}"


def main():
    src = oci.object_storage.ObjectStorageClient(load_config())
    dst = oci.object_storage.ObjectStorageClient(load_config(region=provision.GPU_REGION))
    ns = src.get_namespace().data
    objects = oci.pagination.list_call_get_all_results(
        src.list_objects, ns, SRC_BUCKET, fields="size").data.objects
    sizes = {o.name: o.size for o in objects}
    wanted = [n for n in sizes if n.startswith("models/")]
    for cand in ("laya", "gliner", "semif", "rizzo_flow"):
        latest = f"envs/{cand}/latest.json"
        if latest in sizes:
            obj = json.loads(src.get_object(ns, SRC_BUCKET, latest).data.content)["object"]
            wanted += [latest, obj, obj.replace(".tar.gz", "-env-manifest.json")]
    cuda = "runtimes/rizzo_flow/cuda-latest.json"
    if cuda in sizes:
        wanted += [cuda, json.loads(src.get_object(ns, SRC_BUCKET, cuda).data.content)["object"]]
    existing = {o.name: o.size for o in oci.pagination.list_call_get_all_results(
        dst.list_objects, ns, DST_BUCKET, fields="size").data.objects}
    requests = []
    for name in wanted:
        if name not in sizes:
            continue
        if existing.get(name) == sizes[name] and not name.endswith("latest.json"):
            continue
        r = src.copy_object(ns, SRC_BUCKET, oci.object_storage.models.CopyObjectDetails(
            source_object_name=name, destination_region=provision.GPU_REGION,
            destination_namespace=ns, destination_bucket=DST_BUCKET, destination_object_name=name))
        requests.append((name, r.headers["opc-work-request-id"]))
    total = sum(sizes[n] for n, _ in requests)
    print(f"{len(requests)} cópias iniciadas ({total / 1e9:.2f} GB) para {DST_BUCKET} em {provision.GPU_REGION}")
    if "--wait" in sys.argv:
        pending = dict(requests)
        while pending:
            for name, wr in list(pending.items()):
                status = src.get_work_request(wr).data.status
                if status in ("COMPLETED", "FAILED", "CANCELED"):
                    print(status, name, flush=True)
                    pending.pop(name)
            time.sleep(20)


if __name__ == "__main__":
    main()
