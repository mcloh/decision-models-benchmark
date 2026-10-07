"""Nada sensível nos arquivos versionados: OCIDs, chaves, IPs públicos, namespace ou dados de .secrets/."""
import ipaddress
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [
    re.compile(r"ocid1\.[a-z0-9]+\.oc1\."),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bfingerprint\s*=\s*[0-9a-f:]{20,}"),
]
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def tracked_files():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard"],
                         capture_output=True, text=True, check=True).stdout.split()
    return [ROOT / f for f in out if (ROOT / f).is_file() and not f.startswith(".secrets/")]


def local_secrets() -> list[str]:
    """Valores de .secrets/oci-settings.json não podem aparecer em arquivos versionados."""
    path = ROOT / ".secrets" / "oci-settings.json"
    if not path.is_file():
        return []
    values = []
    for v in json.loads(path.read_text()).values():
        values += [v] + [part for part in str(v).replace("/", " ").split() if len(part) > 5 and part != "root"]
    return values


def test_no_sensitive_content():
    secrets = local_secrets()
    problems = []
    for f in tracked_files():
        try:
            text = f.read_text()
        except UnicodeDecodeError:
            continue
        rel = f.relative_to(ROOT)
        problems += [f"{rel}: {p.pattern}" for p in PATTERNS if p.search(text)]
        problems += [f"{rel}: valor de .secrets/oci-settings.json" for s in secrets if s and s in text]
        for ip in IPV4.findall(text):
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if addr.is_global:
                problems.append(f"{rel}: IP público {ip}")
    assert not problems, "\n".join(problems)
