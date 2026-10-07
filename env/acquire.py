"""Aquisição de artefatos dos candidatos (tarefas 13–16).

Baixa pesos, tokenizadores e licenças nas revisões fixadas, empacota o código-fonte
dos runtimes em commits fixados, calcula SHA-256, envia tudo ao bucket `dmb-artefatos`
e grava o manifesto em env/artifacts-manifest.json.

Uso: PYTHONPATH=infra/oci .venv/bin/python env/acquire.py [--skip-upload]
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import oci
from huggingface_hub import HfApi, snapshot_download
from oci.object_storage import UploadManager

from session import load_config

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "models"
MANIFEST = ROOT / "env" / "artifacts-manifest.json"
BUCKET = "dmb-artefatos"
LICENSE_ALLOWLIST = {"apache-2.0", "mit"}

HF_MODELS = [
    {"candidate": "laya", "repo": "convaiinnovations/laya-multilingual",
     "revision": "1720e3e3357cfe1e281542e223f8273b0890ca34", "allow": None},
    {"candidate": "gliner", "repo": "fastino/GLiNER2.5-multi-Decide",
     "revision": "a35a0cd3b7a0f00f2effc576f454cd48fa98aa5f", "allow": None, "ignore": ["*.png"]},
    {"candidate": "semif", "repo": "Qwen/Qwen3.5-4B",
     "revision": "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a", "allow": None},
    {"candidate": "rizzo_flow", "repo": "rizzoaiacademy/rizzo-flow",
     "revision": "55633c8cbd2b826bd3eefdeb05310450996649df",
     "allow": ["spark-x2.5-4b-rizzo-flow-lora-q8_0.gguf", "LICENSE", "README.md", "training/history.json"],
     "expected_sha256": {"spark-x2.5-4b-rizzo-flow-lora-q8_0.gguf":
                         "dbec3c89d33984772324e65a8ed56b48e958e301b856cb870a7c1b385d01691a"}},
]

GIT_SOURCES = [
    {"candidate": "semif", "repo": "https://github.com/TheoLeeCJ/SemIf-OpenJev",
     "commit": "23cf1f39fc9534fe81437200959b6dfc7106e45a", "license": "mit"},
    {"candidate": "rizzo_flow", "repo": "https://github.com/Rizzo-AI-Academy/rizzo-flow",
     "commit": "b9ba007ee4d2928bbab5b1d8bfe9009c3696b6de", "license": "apache-2.0"},
]


# Runtime llama.cpp do Rizzo Flow (release b11081): arquivos oficiais baixados por
# `rizzo download --only runtime --runtime {cpu,cuda}`, que confere o SHA-256 fixado pelo projeto.
RUNTIME_ARCHIVES = [
    "llama-b11081-bin-ubuntu-x64.tar.gz",
    "llama-b11081-bin-ubuntu-cuda-13.4-x64.tar.gz",
    "cudart-llama-b11081-bin-ubuntu-cuda-13.4-x64.tar.gz",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_hf(spec: dict) -> list[dict]:
    info = HfApi().model_info(spec["repo"], revision=spec["revision"])
    lic = (info.card_data or {}).get("license") if info.card_data else None
    if (lic or "").lower() not in LICENSE_ALLOWLIST:
        sys.exit(f"licença fora da allowlist: {spec['repo']} -> {lic}")
    target = LOCAL / spec["candidate"] / spec["repo"].replace("/", "__") / spec["revision"]
    snapshot_download(spec["repo"], revision=spec["revision"], local_dir=target,
                      allow_patterns=spec.get("allow"), ignore_patterns=spec.get("ignore"))
    entries = []
    for f in sorted(p for p in target.rglob("*") if p.is_file() and ".cache" not in p.parts):
        rel = f.relative_to(target).as_posix()
        digest = sha256(f)
        expected = spec.get("expected_sha256", {}).get(rel)
        if expected and expected != digest:
            sys.exit(f"SHA-256 divergente em {spec['repo']}/{rel}")
        entries.append({
            "candidate": spec["candidate"], "kind": "hf_model", "origin": f"hf://{spec['repo']}",
            "revision": spec["revision"], "license": lic, "path": rel, "sha256": digest,
            "bytes": f.stat().st_size, "local": str(f),
            "object": f"models/{spec['candidate']}/{spec['repo'].replace('/', '__')}/{spec['revision']}/{rel}",
        })
    return entries


def fetch_git(spec: dict) -> list[dict]:
    name = spec["repo"].rstrip("/").split("/")[-1]
    work = LOCAL / "src" / name
    if not (work / ".git").exists():
        subprocess.run(["git", "clone", "-q", spec["repo"], str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "fetch", "-q", "origin", spec["commit"]], check=False)
    subprocess.run(["git", "-C", str(work), "checkout", "-q", spec["commit"]], check=True)
    tarball = LOCAL / "src" / f"{name}-{spec['commit'][:12]}.tar.gz"
    with open(tarball, "wb") as out:
        subprocess.run(["git", "-C", str(work), "archive", "--format=tar.gz",
                        f"--prefix={name}/", spec["commit"]], stdout=out, check=True)
    return [{
        "candidate": spec["candidate"], "kind": "source", "origin": spec["repo"],
        "revision": spec["commit"], "license": spec["license"], "path": tarball.name,
        "sha256": sha256(tarball), "bytes": tarball.stat().st_size, "local": str(tarball),
        "object": f"src/{spec['candidate']}/{tarball.name}",
    }]


def fetch_runtimes() -> list[dict]:
    downloads = LOCAL / "runtimes" / "downloads"
    missing = [a for a in RUNTIME_ARCHIVES if not (downloads / a).is_file()]
    if missing:
        sys.exit(f"runtimes ausentes {missing}: rode `rizzo download --only runtime --runtime cpu|cuda` em models/")
    return [{
        "candidate": "rizzo_flow", "kind": "runtime", "origin": "https://github.com/ggml-org/llama.cpp/releases/tag/b11081",
        "revision": "b11081", "license": "mit", "path": name, "sha256": sha256(downloads / name),
        "bytes": (downloads / name).stat().st_size, "local": str(downloads / name),
        "object": f"runtimes/rizzo_flow/{name}",
    } for name in RUNTIME_ARCHIVES]


def upload(entries: list[dict]) -> None:
    cfg = load_config()
    client = oci.object_storage.ObjectStorageClient(cfg)
    ns = client.get_namespace().data
    manager = UploadManager(client, allow_parallel_uploads=True, parallel_process_count=8)
    for e in entries:
        try:
            head = client.head_object(ns, BUCKET, e["object"])
            if head.headers.get("opc-meta-sha256") == e["sha256"]:
                print("já no bucket:", e["object"])
                continue
        except oci.exceptions.ServiceError as err:
            if err.status != 404:
                raise
        if sha256(Path(e["local"])) != e["sha256"]:
            sys.exit(f"{e['local']} mudou depois do cálculo do hash; abortando o envio")
        print(f"enviando {e['object']} ({e['bytes'] / 1e9:.2f} GB)", flush=True)
        manager.upload_file(ns, BUCKET, e["object"], e["local"],
                            metadata={"sha256": e["sha256"], "revision": e["revision"]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-upload", action="store_true")
    args = ap.parse_args()

    entries = []
    for spec in HF_MODELS:
        print("baixando", spec["repo"], flush=True)
        entries += fetch_hf(spec)
    for spec in GIT_SOURCES:
        print("empacotando", spec["repo"], flush=True)
        entries += fetch_git(spec)
    entries += fetch_runtimes()
    if not args.skip_upload:
        upload(entries)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = {
        "schema": "dmb-artifacts-v1",
        "acquired_at": now,
        "bucket": BUCKET,
        "license_allowlist": sorted(LICENSE_ALLOWLIST),
        "artifacts": [{k: v for k, v in e.items() if k != "local"} for e in entries],
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    total = sum(e["bytes"] for e in entries)
    print(f"{len(entries)} artefatos, {total / 1e9:.2f} GB; manifesto em {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
