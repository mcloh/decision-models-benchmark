#!/usr/bin/env bash
# Máquina local = IDE + repositório; execução na VM dmb-vm.
#   infra/vm/remote.sh sync              # envia o repositório (sem .secrets, models, venvs)
#   infra/vm/remote.sh run <comando...>  # sincroniza e roda o comando na VM, dentro do repositório
#   infra/vm/remote.sh ssh               # abre um shell na VM
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KEY="$ROOT/.secrets/ssh/ssh-key-oci.key"
IP="$(grep -oE 'IP público [0-9.]+' "$ROOT/.secrets/artefatos-OCI.md" | head -1 | awk '{print $3}')"
[ -n "$IP" ] || { echo "IP da VM não encontrado em .secrets/artefatos-OCI.md" >&2; exit 1; }
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 "opc@$IP")
REMOTE_DIR=/data/repo

sync() {
  rsync -az --delete -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
    --exclude '.git/' --exclude '.secrets/' --exclude 'models/' --exclude '.venv*/' \
    --exclude '__pycache__/' --exclude 'reports/sanity/' --exclude 'runs/' \
    "$ROOT/" "opc@$IP:$REMOTE_DIR/"
}

case "${1:-}" in
  sync) sync ;;
  run) shift; sync; "${SSH[@]}" "cd $REMOTE_DIR && bash -lc $(printf '%q' "$*")" ;;
  ssh) "${SSH[@]}" ;;
  *) sed -n '2,6p' "$0"; exit 1 ;;
esac
