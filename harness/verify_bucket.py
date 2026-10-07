"""Audita o bucket de artefatos: o conteúdo real de cada objeto bate com o SHA-256 do manifesto?

Uso (na VM ou num job): python -m harness.verify_bucket
"""
import hashlib
import json
import sys
from pathlib import Path

from harness.objstore import client

MANIFEST = Path(__file__).resolve().parents[1] / "env" / "artifacts-manifest.json"


def main():
    c, ns = client()
    manifest = json.loads(MANIFEST.read_text())
    bad = 0
    for a in manifest["artifacts"]:
        h = hashlib.sha256()
        for chunk in c.get_object(ns, manifest["bucket"], a["object"]).data.raw.stream(1 << 22, decode_content=False):
            h.update(chunk)
        ok = h.hexdigest() == a["sha256"]
        bad += not ok
        print(("ok  " if ok else "DIVERGENTE  ") + a["object"], flush=True)
    print(f"{len(manifest['artifacts']) - bad}/{len(manifest['artifacts'])} artefatos conferem")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
