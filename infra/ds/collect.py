"""Coleta os resumos de avaliação (dmb-resultados e dmb-resultados-gru) para reports/<destino>/.

Para cada (candidato, dispositivo, partição) usa a execução mais recente bem-sucedida com o
número de exemplos pedido. Gera os JSONs, as predições e um README.md com a tabela comparativa.

Uso: PYTHONPATH=infra/oci .venv/bin/python infra/ds/collect.py --split dev --examples 50 --dest reports/pilot
"""
import argparse
import json
from pathlib import Path

import oci

import provision
from session import load_config

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [(provision.REGION, "dmb-resultados"), (provision.GPU_REGION, f"dmb-resultados{provision.GPU_SUFFIX}")]


def fmt(v, nd=1):
    return "—" if v is None else f"{v:.{nd}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    ap.add_argument("--examples", type=int)
    ap.add_argument("--dest", required=True)
    args = ap.parse_args()
    dest = ROOT / args.dest
    dest.mkdir(parents=True, exist_ok=True)
    latest = {}
    for region, bucket in SOURCES:
        c = oci.object_storage.ObjectStorageClient(load_config(region=region))
        ns = c.get_namespace().data
        names = [o.name for o in oci.pagination.list_call_get_all_results(
            c.list_objects, ns, bucket, prefix="runs/").data.objects]
        for n in names:
            fname = n.rsplit("/", 1)[-1]
            if not (fname.startswith("summary-") and fname.endswith(f"-{args.split}.json")):
                continue
            s = json.loads(c.get_object(ns, bucket, n).data.content)
            if args.examples and s["examples"] != args.examples:
                continue
            if s.get("operational_env"):  # execuções exploratórias com parâmetros alterados ficam de fora
                continue
            key = (s["candidate"]["name"], s["device"])
            run_id = n.split("/")[1]
            if key not in latest or run_id > latest[key][0]:
                pred = n.replace("summary-", "predictions-").replace(".json", ".jsonl")
                latest[key] = (run_id, s, c, ns, bucket, pred, region)
    rows = []
    for (cand, dev), (run_id, s, c, ns, bucket, pred, region) in sorted(latest.items()):
        s["oci"] = {"region": region, "run_id": run_id}
        (dest / f"summary-{cand}-{dev}.json").write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n")
        try:
            (dest / f"predictions-{cand}-{dev}.jsonl").write_bytes(c.get_object(ns, bucket, pred).data.content)
        except oci.exceptions.ServiceError:
            pass
        q, lat, cal = s["quality"], s["latency_ms"], s.get("calibration_raw", {})
        rows.append(f"| {cand} | {dev} | {s.get('precision') or '—'} | {q.get('n', 0)} | "
                    f"{fmt(q.get('accuracy', 0) * 100)}% | {fmt(q.get('macro_f1', 0) * 100)}% | "
                    f"{fmt(cal.get('ece'), 3)} | {fmt(lat['p50'])} | {fmt(lat['p95'])} | {fmt(lat['p99'])} | "
                    f"{fmt(s['load_seconds'])} | {fmt(s.get('rss_peak_mib'), 0)} | {fmt(s.get('gpu_mem_peak_mib'), 0)} | "
                    f"{sum(s['errors'].values())} | {s['truncated']} |")
    table = ("| Candidato | Disp. | Precisão | n | Acurácia | Macro F1 | ECE (bruto) | p50 ms | p95 ms | p99 ms | "
             "Carga s | RAM pico MiB | GPU pico MiB | Erros | Truncados |\n"
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n" + "\n".join(rows))
    readme = (f"# Resultados — partição `{args.split}`"
              + (f", {args.examples} exemplos" if args.examples else "") + "\n\n"
              "Gerado por `infra/ds/collect.py` a partir dos buckets de resultados. CPU: us-chicago-1 "
              "(`VM.Standard.E4.Flex`, 8 OCPU, sub-rede privada). GPU: sa-saopaulo-1 (`VM.GPU.A10.1`). "
              "Lote 1; latências excluem os exemplos de aquecimento. Probabilidades ainda sem calibração.\n\n"
              + table + "\n")
    (dest / "README.md").write_text(readme)
    print(readme)


if __name__ == "__main__":
    main()
