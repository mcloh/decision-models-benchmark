#!/usr/bin/env bash
# Entrada dos jobs de benchmark: usa o Python base do job (SDK OCI + resource principal)
# para o processo pai; a inferência roda no ambiente do candidato (ver harness/job.py).
set -euo pipefail
cd "$(dirname "$0")/../.."
exec /opt/conda/bin/python3 -m harness.job
