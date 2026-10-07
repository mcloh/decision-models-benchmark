# Imagem de um candidato do benchmark (tarefas 11–12).
# Uma imagem por candidato: as dependências do SemIf (transformers 5.x) e do GLiNER
# (transformers<5) não convivem. Os pesos NÃO entram na imagem: o job os baixa do bucket
# dmb-artefatos e confere o SHA-256 contra env/artifacts-manifest.json.
#
#   docker build -f env/Dockerfile --build-arg CANDIDATE=laya -t dmb-laya .
#
# syntax=docker/dockerfile:1.7
ARG BASE_IMAGE=python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
FROM ${BASE_IMAGE}

ARG BASE_IMAGE
ARG CANDIDATE
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu128
RUN test -n "${CANDIDATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    USE_TF=0 \
    DMB_CANDIDATE=${CANDIDATE} \
    DMB_BASE_IMAGE=${BASE_IMAGE} \
    DMB_MODELS_ROOT=/models \
    RIZZO_LLAMA_DIR=/opt/runtimes/llama-b11081-linux-x64-cuda

RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/dmb
COPY env/requirements/ env/requirements/
RUN pip install -r env/requirements/common.txt \
 && pip install --extra-index-url ${TORCH_INDEX} -r env/requirements/${CANDIDATE}.txt

# Código-fonte dos runtimes em commits fixados (mesmos tarballs do bucket).
COPY models/src/*.tar.gz /opt/src/
COPY models/runtimes/llama-b11081-linux-x64-cpu /opt/runtimes/llama-b11081-linux-x64-cpu
COPY models/runtimes/llama-b11081-linux-x64-cuda /opt/runtimes/llama-b11081-linux-x64-cuda
RUN set -e; cd /opt/src; \
    case "${CANDIDATE}" in \
      semif) tar xzf SemIf-OpenJev-*.tar.gz && pip install --no-deps ./SemIf-OpenJev ;; \
      rizzo_flow) tar xzf rizzo-flow-*.tar.gz && pip install --no-deps ./rizzo-flow ;; \
    esac; \
    if [ "${CANDIDATE}" != rizzo_flow ]; then rm -rf /opt/runtimes; fi; \
    rm -f /opt/src/*.tar.gz

COPY pyproject.toml ./
COPY dmb/ dmb/
COPY adapters/ adapters/
COPY harness/ harness/
COPY contracts/ contracts/
COPY infra/oci/session.py infra/oci/session.py
COPY config/ config/
COPY env/artifacts-manifest.json env/artifacts-manifest.json

# Manifesto de versões da imagem (tarefa 12).
RUN python -m harness.image_manifest > /opt/dmb/image-manifest.json

ENTRYPOINT ["python", "-m", "harness.job"]
