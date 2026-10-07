#!/usr/bin/env bash
# Preparação idempotente da VM de trabalho (Oracle Linux 9). Rodar na VM:
#   bash infra/vm/bootstrap.sh
set -euo pipefail
sudo dnf install -y -q git rsync tmux jq python3.12 python3.12-pip python3.12-devel gcc gcc-c++ >/dev/null
[ -d "$HOME/.venv-oci" ] || python3.12 -m venv "$HOME/.venv-oci"
"$HOME/.venv-oci/bin/pip" install -q --upgrade pip
"$HOME/.venv-oci/bin/pip" install -q "oci==2.187.2" oci-cli "huggingface_hub==0.36.2" jsonschema fastapi uvicorn pyyaml pytest httpx
grep -q OCI_CLI_AUTH "$HOME/.bashrc" || cat >> "$HOME/.bashrc" <<'RC'
export OCI_CLI_AUTH=instance_principal
export DMB_OCI_AUTH=instance_principal
export PATH=$HOME/.venv-oci/bin:$PATH
RC
echo "bootstrap ok: $(python3.12 --version), oci $("$HOME/.venv-oci/bin/python" -c 'import oci;print(oci.__version__)')"
