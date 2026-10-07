"""Ponto de entrada dos jobs do OCI Data Science (tarefas 10, 17–19).

O processo pai fala só com o Object Storage (via Service Gateway): baixa os artefatos do
candidato, confere o SHA-256 contra o manifesto, roda o gate de egresso e, no fim, envia
resultados e logs. A inferência roda num processo filho com o bloqueio de rede ativo.

Variáveis: DMB_CANDIDATE, DMB_MODE (gate|sanity), DMB_DEVICE (auto|cpu|cuda), DMB_RUN_ID,
DMB_MODELS_ROOT. O ambiente Python do candidato vem de dmb-artefatos/envs/<candidato>/latest.json,
publicado pelo job de build (infra/ds/build_env.sh).
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "env" / "artifacts-manifest.json"
BUCKET_ARTIFACTS = os.environ.get("DMB_BUCKET_ARTIFACTS", "dmb-artefatos")
BUCKET_RESULTS = os.environ.get("DMB_BUCKET_RESULTS", "dmb-resultados")
EGRESS_PROBES = [("huggingface.co", 443), ("pypi.org", 443), ("github.com", 443)]


def oci_clients():
    import oci

    if os.environ.get("OCI_RESOURCE_PRINCIPAL_VERSION"):
        signer = oci.auth.signers.get_resource_principals_signer()
        client = oci.object_storage.ObjectStorageClient({}, signer=signer)
    else:
        sys.path.insert(0, str(ROOT / "infra" / "oci"))
        from session import load_config
        client = oci.object_storage.ObjectStorageClient(load_config())
    return client, client.get_namespace().data


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_artifacts(candidate: str, models_root: Path) -> dict:
    """Tarefa 18: só artefatos do manifesto, com hash conferido."""
    client, ns = oci_clients()
    manifest = json.loads(MANIFEST.read_text())
    entries = [a for a in manifest["artifacts"] if a["candidate"] == candidate and a["kind"] == "hf_model"]
    started, total = time.perf_counter(), 0
    for a in entries:
        target = models_root / a["object"].removeprefix("models/")
        if not (target.is_file() and target.stat().st_size == a["bytes"] and sha256(target) == a["sha256"]):
            target.parent.mkdir(parents=True, exist_ok=True)
            obj = client.get_object(ns, BUCKET_ARTIFACTS, a["object"])
            with target.open("wb") as f:
                for chunk in obj.data.raw.stream(1 << 22, decode_content=False):
                    f.write(chunk)
            if sha256(target) != a["sha256"]:
                raise SystemExit(f"SHA-256 divergente: {a['object']}")
        total += a["bytes"]
    return {"files": len(entries), "bytes": total, "seconds": round(time.perf_counter() - started, 1)}


def install_env(candidate: str) -> tuple[Path, dict]:
    """Baixa o ambiente publicado pelo build, confere o SHA-256 e extrai em $HOME/envs."""
    import tarfile

    from harness import objstore

    home = Path(os.environ.get("HOME", "/home/datascience"))
    latest = json.loads(objstore.get(BUCKET_ARTIFACTS, f"envs/{candidate}/latest.json",
                                     Path("/tmp/latest.json")).read_text())
    if Path(latest["home"]) != home:
        raise SystemExit(f"ambiente construído para HOME={latest['home']}, job em {home}")
    tarball = objstore.get(BUCKET_ARTIFACTS, latest["object"], Path("/tmp/env.tar.gz"))
    if sha256(tarball) != latest["sha256"]:
        raise SystemExit("SHA-256 do ambiente divergente")
    with tarfile.open(tarball) as tar:
        tar.extractall(home)
    tarball.unlink()
    return home / "envs" / candidate / "bin" / "python", latest


def install_rizzo_cuda_runtime() -> Path:
    """llama.cpp CUDA compilado para a imagem dos jobs (infra/ds/build_llama_cuda.sh)."""
    import tarfile

    from harness import objstore

    home = Path(os.environ.get("HOME", "/home/datascience"))
    latest = json.loads(objstore.get(BUCKET_ARTIFACTS, "runtimes/rizzo_flow/cuda-latest.json",
                                     Path("/tmp/cuda-latest.json")).read_text())
    tarball = objstore.get(BUCKET_ARTIFACTS, latest["object"], Path("/tmp/llama-cuda.tar.gz"))
    if sha256(tarball) != latest["sha256"]:
        raise SystemExit("SHA-256 do runtime CUDA divergente")
    with tarfile.open(tarball) as tar:
        tar.extractall(home)
    return home / latest["dir"]


def has_gpu() -> bool:
    return subprocess.run(["sh", "-c", "command -v nvidia-smi && nvidia-smi -L"],
                          capture_output=True).returncode == 0


def egress_gate() -> dict:
    """Tarefas 17 e 19: o gate passa só se nenhuma saída para a internet funcionar."""
    probes = []
    for host, port in EGRESS_PROBES:
        try:
            with socket.create_connection((host, port), timeout=5):
                outcome = "CONECTOU"
        except OSError as error:
            outcome = f"bloqueado ({type(error).__name__})"
        probes.append({"host": host, "port": port, "outcome": outcome})
    return {"passed": all(p["outcome"] != "CONECTOU" for p in probes), "probes": probes}


def upload_dir(local: Path, bucket: str, prefix: str) -> list[str]:
    client, ns = oci_clients()
    sent = []
    for f in sorted(p for p in local.rglob("*") if p.is_file()):
        name = f"{prefix}/{f.relative_to(local).as_posix()}"
        with f.open("rb") as body:
            client.put_object(ns, bucket, name, body)
        sent.append(name)
    return sent


def main():
    candidate = os.environ["DMB_CANDIDATE"]
    mode = os.environ.get("DMB_MODE", "sanity")
    device = os.environ.get("DMB_DEVICE", "auto")
    run_id = os.environ.setdefault(
        "DMB_RUN_ID", f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{candidate}-{mode}")
    models_root = Path(os.environ.get("DMB_MODELS_ROOT", Path.home() / "models"))
    if device == "auto":
        device = "cuda" if has_gpu() else "cpu"
    out = Path("/tmp/dmb-out") / run_id
    out.mkdir(parents=True, exist_ok=True)

    run = {"run_id": run_id, "candidate": candidate, "mode": mode, "device": device,
           "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    image_manifest = ROOT / "image-manifest.json"
    if image_manifest.is_file():
        run["image"] = json.loads(image_manifest.read_text())

    run["egress_gate"] = egress_gate()
    # DMB_ISOLATION=app: só onde não há sub-rede privada (região de GPU sem VCN disponível).
    # A rede tem saída; o isolamento fica a cargo do bloqueio no processo (dmb.offline + self_test).
    run["isolation"] = os.environ.get("DMB_ISOLATION", "network")
    if not run["egress_gate"]["passed"] and mode != "gate" and run["isolation"] != "app":
        run["status"] = "abortado: gate de egresso reprovado"
    else:
        if mode != "gate":
            run["artifacts"] = fetch_artifacts(candidate, models_root)
            python, run["env"] = install_env(candidate)
            child_env = dict(os.environ)
            if candidate == "rizzo_flow":
                # CPU: binário oficial; CUDA: build próprio (o oficial exige GLIBC 2.38).
                child_env["RIZZO_LLAMA_DIR"] = str(
                    install_rizzo_cuda_runtime() if device == "cuda"
                    else python.parents[1] / "runtimes" / "llama-b11081-linux-x64-cpu")
                run["rizzo_runtime"] = child_env["RIZZO_LLAMA_DIR"]
            cmd = [str(python), "-m", f"harness.{mode}", "--candidate", candidate,
                   "--models-root", str(models_root), "--device", device, "--out", str(out)]
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=child_env)
            print(proc.stdout[-4000:])
            print(proc.stderr[-4000:], file=sys.stderr)
            (out / "stdout.log").write_text(proc.stdout)
            (out / "stderr.log").write_text(proc.stderr)
            run["exit_code"] = proc.returncode
            run["status"] = "ok" if proc.returncode == 0 else "falhou"
        else:
            run["status"] = "ok" if run["egress_gate"]["passed"] else "gate reprovado"

    run["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (out / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: run[k] for k in ("run_id", "status", "egress_gate")}, ensure_ascii=False))
    sent = upload_dir(out, BUCKET_RESULTS, f"runs/{run_id}")
    print(f"{len(sent)} arquivos enviados para {BUCKET_RESULTS}/runs/{run_id}")
    sys.exit(0 if run["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
