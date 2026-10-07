"""Acesso mínimo ao Object Storage, usável com o Python base dos jobs (resource principal).

  python -m harness.objstore get <bucket> <objeto> <destino>
  python -m harness.objstore put <bucket> <objeto> <origem> [--sha256]
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def client():
    import oci

    if os.environ.get("OCI_RESOURCE_PRINCIPAL_VERSION"):
        c = oci.object_storage.ObjectStorageClient({}, signer=oci.auth.signers.get_resource_principals_signer())
    elif os.environ.get("DMB_OCI_AUTH") == "instance_principal":
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        c = oci.object_storage.ObjectStorageClient({"region": signer.region}, signer=signer)
    else:
        sys.path.insert(0, str(ROOT / "infra" / "oci"))
        from session import load_config
        c = oci.object_storage.ObjectStorageClient(load_config())
    return c, c.get_namespace().data


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def get(bucket: str, name: str, dest: Path) -> Path:
    c, ns = client()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    obj = c.get_object(ns, bucket, name)
    with dest.open("wb") as f:
        for chunk in obj.data.raw.stream(1 << 22, decode_content=False):
            f.write(chunk)
    return dest


def put(bucket: str, name: str, src: Path, metadata: dict | None = None) -> None:
    from oci.object_storage import UploadManager

    c, ns = client()
    UploadManager(c, allow_parallel_uploads=True, parallel_process_count=8).upload_file(
        ns, bucket, name, str(src), metadata=metadata or {})


if __name__ == "__main__":
    cmd, bucket, name, path = sys.argv[1:5]
    if cmd == "get":
        get(bucket, name, Path(path))
    elif cmd == "put":
        meta = {"sha256": sha256(Path(path))} if "--sha256" in sys.argv else {}
        put(bucket, name, Path(path), meta)
        print(meta.get("sha256", ""))
    else:
        sys.exit(__doc__)
