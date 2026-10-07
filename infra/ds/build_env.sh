#!/usr/bin/env bash
# Job de build (rede gerenciada, com internet): cria o ambiente Python do candidato com as
# versões fixadas de env/requirements/, empacota e publica em dmb-artefatos/envs/<candidato>/.
# Os jobs de benchmark (sub-rede privada) só baixam esse pacote; nunca instalam da internet.
set -euo pipefail
CAND="${DMB_CANDIDATE:?defina DMB_CANDIDATE}"
CODE="$(cd "$(dirname "$0")/../.." && pwd)"
BASE_PY=/opt/conda/bin/python3
ENV_DIR="$HOME/envs/$CAND"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
cd "$CODE"

echo "== build $CAND em $ENV_DIR (código $DMB_CODE_REV)"
rm -rf "$ENV_DIR"
"$BASE_PY" -m venv "$ENV_DIR"
"$ENV_DIR/bin/pip" install -q --upgrade "pip==25.2"
"$ENV_DIR/bin/pip" install -q -r env/requirements/common.txt "pytest==8.4.2" "httpx==0.28.1"
"$ENV_DIR/bin/pip" install -q --extra-index-url https://download.pytorch.org/whl/cu128 -r "env/requirements/$CAND.txt"

src_object() {  # objeto do tarball de código-fonte do candidato, segundo o manifesto
  "$BASE_PY" -c "import json,sys; m=json.load(open('env/artifacts-manifest.json')); print(next(a['object'] for a in m['artifacts'] if a['candidate']=='$CAND' and a['kind']=='source'))"
}
case "$CAND" in
  semif|rizzo_flow)
    OBJ="$(src_object)"
    "$BASE_PY" -m harness.objstore get dmb-artefatos "$OBJ" /tmp/src.tar.gz
    mkdir -p /tmp/src && tar xzf /tmp/src.tar.gz -C /tmp/src
    "$ENV_DIR/bin/pip" install -q --no-deps /tmp/src/*/
    ;;
esac
if [ "$CAND" = rizzo_flow ]; then
  # Runtime llama.cpp b11081 (CPU e CUDA), com o SHA-256 conferido pelo próprio Rizzo Flow.
  (cd "$ENV_DIR" && "$ENV_DIR/bin/rizzo" download --only runtime --runtime cpu \
     && "$ENV_DIR/bin/rizzo" download --only runtime --runtime cuda && rm -rf runtimes/downloads)
fi

"$ENV_DIR/bin/python" -m harness.image_manifest > "$ENV_DIR/env-manifest.json"
"$ENV_DIR/bin/python" -m pytest -q tests 2>&1 | tail -2

TARBALL="/tmp/$CAND-env.tar.gz"
tar czf "$TARBALL" -C "$HOME" "envs/$CAND"
OBJECT="envs/$CAND/$STAMP.tar.gz"
SHA="$("$BASE_PY" -m harness.objstore put dmb-artefatos "$OBJECT" "$TARBALL" --sha256)"
SIZE="$(stat -c %s "$TARBALL")"
cat > /tmp/latest.json <<JSON
{"candidate": "$CAND", "object": "$OBJECT", "sha256": "$SHA", "bytes": $SIZE,
 "built_at": "$STAMP", "code_rev": "${DMB_CODE_REV:-}", "python": "$("$ENV_DIR/bin/python" --version 2>&1)",
 "home": "$HOME"}
JSON
"$BASE_PY" -m harness.objstore put dmb-artefatos "envs/$CAND/latest.json" /tmp/latest.json
"$BASE_PY" -m harness.objstore put dmb-artefatos "envs/$CAND/$STAMP-env-manifest.json" "$ENV_DIR/env-manifest.json"
cat /tmp/latest.json
echo "== ok"
