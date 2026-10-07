"""Sessão OCI do benchmark a partir das credenciais em .secrets/oci-credentials/."""
import configparser
from pathlib import Path

import oci

ROOT = Path(__file__).resolve().parents[2]
CRED_DIR = ROOT / ".secrets" / "oci-credentials"
REGION = "us-chicago-1"


def load_config(region: str = REGION, profile: str = "DEFAULT") -> dict:
    parser = configparser.ConfigParser()
    parser.read(CRED_DIR / "profile.config")
    cfg = dict(parser[profile])
    key_file = cfg.get("key_file", "").split("#")[0].strip()
    if not key_file or not Path(key_file).expanduser().is_file():
        keys = [p for p in CRED_DIR.glob("*.pem") if not p.name.endswith("_public.pem")]
        if len(keys) != 1:
            raise RuntimeError(f"esperada 1 chave privada em {CRED_DIR}, encontradas {len(keys)}")
        key_file = str(keys[0])
    cfg["key_file"] = key_file
    cfg["region"] = region
    oci.config.validate_config(cfg)
    return cfg
