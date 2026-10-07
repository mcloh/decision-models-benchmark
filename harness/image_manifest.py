"""Imprime o manifesto de versões do ambiente atual (tarefa 12)."""
import json
import os
import platform
import sys
from importlib import metadata


def collect() -> dict:
    packages = sorted((d.metadata["Name"], d.version) for d in metadata.distributions())
    info = {
        "candidate": os.environ.get("DMB_CANDIDATE"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "base_image": os.environ.get("DMB_BASE_IMAGE"),
        "packages": {name: version for name, version in packages},
    }
    try:
        import torch
        info["torch_cuda"] = torch.version.cuda
        info["cudnn"] = torch.backends.cudnn.version()
    except ImportError:
        pass
    return info


if __name__ == "__main__":
    json.dump(collect(), sys.stdout, indent=2)
    print()
