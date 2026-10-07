# 05 — Ambiente de execução

A máquina local é **só IDE e repositório**. Todo script de benchmark roda na OCI (região `us-chicago-1`, compartment `decision-models`), no OCI Data Science.

## Componentes

| Componente | Rede | Uso |
|------------|------|-----|
| **Jobs de build** (`infra/ds/build_env.sh`) | Rede gerenciada do serviço, com internet | Criam o ambiente Python de cada candidato com as versões fixadas em `env/requirements/` e o publicam em `dmb-artefatos/envs/<candidato>/` (pacote + `latest.json` com SHA-256 + manifesto de versões) |
| **Jobs de benchmark** (`infra/ds/run_job.sh` → `harness/job.py`) | Sub-rede privada `dmb-subnet-jobs`, **sem internet**, só Service Gateway | Gate de egresso, download dos pesos e do ambiente do bucket (SHA-256 conferido), inferência com bloqueio de rede no processo e envio dos resultados para `dmb-resultados/runs/<run_id>/` |
| **Notebook `dmb-notebook-cpu`** | Rede gerenciada | Análise interativa dos resultados. Um notebook de GPU é criado só quando houver trabalho interativo em GPU |
| Máquina local | — | Edição, testes unitários rápidos e disparo dos jobs (`infra/ds/jobs.py`) |

O código vai para cada job como artefato zip, gerado na hora a partir do repositório local, sem `.secrets/`, `models/` e venvs. Dentro do job, o processo pai usa o Python base do serviço (3.11.9, com SDK OCI e resource principal). A inferência roda no Python do ambiente do candidato.

## Comandos

```bash
# job genérico (CPU flex ou GPU), com espera e logs
PYTHONPATH=infra/oci .venv/bin/python infra/ds/jobs.py run --name <nome> --entrypoint <script> \
    [--shape VM.Standard.E4.Flex --ocpus 4 --memory 32 | --shape VM.GPU.A10.1] [--private] \
    [--env DMB_CANDIDATE=laya DMB_MODE=sanity DMB_DEVICE=auto] [--wait]

# build do ambiente de um candidato
... jobs.py run --name build-laya --entrypoint infra/ds/build_env.sh --ocpus 4 --memory 32 --env DMB_CANDIDATE=laya

# sanidade de um candidato na sub-rede privada (CPU ou GPU)
... jobs.py run --name sanity-laya --entrypoint infra/ds/run_job.sh --private \
    --env DMB_CANDIDATE=laya DMB_MODE=sanity --wait
... jobs.py run --name sanity-laya-gpu --entrypoint infra/ds/run_job.sh --private --shape VM.GPU.A10.1 \
    --env DMB_CANDIDATE=laya DMB_MODE=sanity --wait
```

## GPU (sa-saopaulo-1)

| Item | Valor |
|------|-------|
| Shape | `VM.GPU.A10.1`, **uma GPU por vez** (limite da região) — `infra/ds/gpu_queue.py` enfileira |
| Dados | `dmb-artefatos-gru` (réplica server-side com `infra/oci/replicate.py`), resultados em `dmb-resultados-gru` |
| Rede | Gerenciada (limite de VCNs da região esgotado). Isolamento no processo + autoteste `process_guard` (`DMB_ISOLATION=app`) |
| Rizzo Flow em CUDA | O binário oficial do llama.cpp exige GLIBC 2.38; a imagem dos jobs tem 2.34. `infra/ds/build_llama_cuda.sh` compila o mesmo commit (`161755f`) com CUDA 12.8, sysroot glibc 2.17 e libstdc++ estática (maior GLIBC exigida: 2.27), publicado em `runtimes/rizzo_flow/cuda-latest.json` |

```bash
PYTHONPATH=infra/oci:infra/ds .venv/bin/python infra/ds/gpu_queue.py sanity laya gliner semif rizzo_flow
```

## Dados sintéticos (na VM)

```bash
export DMB_OCI_AUTH=instance_principal DMB_COMPARTMENT_OCID=<ocid do compartment>
python -m datagen.generate --out /data/runs/datagen-v1      # OCI Generative AI (us-chicago-1)
python -m datagen.prepare  --run /data/runs/datagen-v1
python -m datagen.annotate --run /data/runs/datagen-v1
python -m datagen.build    --run /data/runs/datagen-v1 --freeze
```

## Configuração local sensível

Fora do Git, em `.secrets/`: credenciais OCI, chaves SSH, o catálogo de artefatos com OCIDs (`artefatos-OCI.md`) e `oci-settings.json` (caminho do compartimento pai e CIDR autorizado para SSH; variáveis `DMB_PARENT_COMPARTMENT` e `DMB_SSH_CIDR` têm precedência). `tests/test_sensitive.py` falha se OCIDs, chaves, IPs públicos ou valores de `.secrets/oci-settings.json` aparecerem em arquivos versionados.

## VM de trabalho

| Item | Valor |
|------|-------|
| Instância | `instance-20261007-1206`: `VM.Standard.E6.Flex`, 8 OCPU (16 vCPU), 88 GB, Oracle Linux 9, sub-rede `dmb-subnet-dev` (SSH só do IP autorizado) |
| Disco | Boot volume de 200 GB (raiz `/`) + block volume `dmb-compute-vol` de 1 TB (iSCSI, XFS) montado em **`/data`**: `models/`, `envs/`, `runs/`, `repo/` |
| Acesso à OCI | Instance principal (política `dmb-workloads`), sem chave de API na VM |
| Preparação | `infra/vm/bootstrap.sh` (Python 3.12, git, rsync, SDK OCI em `~/.venv-oci`) |

A VM roda o trabalho de CPU que não precisa do isolamento de rede dos jobs: preparação de dados, análise e orquestração. Do lado local:

```bash
infra/vm/remote.sh sync                      # envia o repositório para /data/repo (sem .secrets, models, venvs)
infra/vm/remote.sh run '<comando>'           # sincroniza e executa na VM
infra/vm/remote.sh ssh                       # shell na VM
```

A VM foi criada pelo console: o lançamento de instâncias pela API, com a chave do usuário, é negado neste compartment (`404` em `LaunchInstance`). Por isso `infra/oci/provision.py` só registra a VM e seus volumes no catálogo, sem tentar criá-la. O `env/Dockerfile` (uma imagem por candidato) fica como alternativa caso se queira contêineres próprios (BYOC/OCIR).

## Divisão do trabalho

| Trabalho | Onde |
|----------|------|
| Execuções que valem como medição (piloto, dev, calibração, teste final) | Jobs do Data Science na sub-rede privada, em CPU (`VM.Standard.E4.Flex`) ou GPU (`VM.GPU.A10.1`) |
| Builds de ambiente | Jobs com rede gerenciada |
| Preparação de dados, análise, relatórios | VM (`/data`) ou notebook |
| Edição e disparo | Máquina local |
