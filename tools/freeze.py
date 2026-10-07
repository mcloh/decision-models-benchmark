"""Congela a configuração antes da abertura do teste final (tarefa 62).

Grava config/frozen.json com o SHA-256 da configuração, da calibração, das partições, do manifesto
de artefatos, do código dos adaptadores, do contrato e do executor, e com os ambientes publicados de
cada candidato. A presença desse arquivo libera a partição de teste em harness/evaluate.py; depois
do congelamento, prompts, opções, pesos, calibradores e limiares não mudam (os testes conferem).

Uso: PYTHONPATH=infra/oci .venv/bin/python tools/freeze.py
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "config" / "frozen.json"
TRACKED = ["config/benchmark.yaml", "config/calibration.json", "data/splits/MANIFEST.json",
           "env/artifacts-manifest.json", "contracts/jev/schemas/request.schema.json",
           "contracts/jev/schemas/response.schema.json", "harness/evaluate.py", "dmb/canonical.py",
           "dmb/jev.py", "dmb/server.py", "dmb/adapter.py", "adapters/laya/adapter.py",
           "adapters/semif/adapter.py", "adapters/gliner/adapter.py", "adapters/rizzo_flow/adapter.py"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_hashes() -> dict:
    return {p: sha(ROOT / p) for p in TRACKED}


def env_snapshot() -> dict:
    sys.path.insert(0, str(ROOT))
    from harness import objstore
    out = {}
    for cand in ("laya", "gliner", "semif", "rizzo_flow"):
        tmp = Path("/tmp") / f"freeze-{cand}-latest.json"
        out[cand] = json.loads(objstore.get("dmb-artefatos", f"envs/{cand}/latest.json", tmp).read_text())
    cuda = Path("/tmp/freeze-cuda-latest.json")
    out["rizzo_flow_cuda_runtime"] = json.loads(
        objstore.get("dmb-artefatos", "runtimes/rizzo_flow/cuda-latest.json", cuda).read_text())
    return out


def main():
    if FROZEN.exists():
        sys.exit("configuração já congelada: config/frozen.json existe")
    missing = [p for p in TRACKED if not (ROOT / p).is_file()]
    if missing:
        sys.exit(f"faltam arquivos para congelar: {missing}")
    frozen = {"frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "files": current_hashes(), "environments": env_snapshot()}
    FROZEN.write_text(json.dumps(frozen, indent=2, ensure_ascii=False) + "\n")
    print(f"congelado: {len(frozen['files'])} arquivos e {len(frozen['environments'])} ambientes")


if __name__ == "__main__":
    main()
