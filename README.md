# Benchmark de modelos de decisão em PT-BR para roteamento em orquestradores multiagente

## Apresentação

Num sistema multiagente, o **orquestrador** decide a cada turno para onde vai a mensagem do usuário: qual intenção ela expressa, qual agente deve atendê-la e quando é melhor perguntar antes de agir. Essas decisões ficam no caminho síncrono de toda conversa e precisam ser rápidas, baratas e confiáveis.

Este benchmark avalia se **modelos de decisão *open source***, do tipo "System 1", podem cumprir esse papel em português do Brasil, no lugar de chamadas a LLMs generalistas. São modelos que respondem a uma pergunta com opções definidas em tempo de execução e devolvem uma distribuição de probabilidades, sem gerar texto, no padrão do contrato JEV `POST /v1/systemone`.

**Candidatos**

| Candidato | Modelo | Tipo |
|---|---|---|
| **SemIf** | `SemIf-OpenJev` + `Qwen/Qwen3.5-4B` (modo `direct`) | LLM de 4B, logits das opções |
| **Rizzo Flow** | `rizzoaiacademy/rizzo-flow` (Spark-X2.5 4B + LoRA, GGUF Q8_0) | LLM de 4B, logits das opções |
| **Laya** | `convaiinnovations/laya-multilingual` | Encoder de 322M com cabeça de decisão |
| **GLiNER** | `fastino/GLiNER2.5-multi-Decide` | Encoder de 287M, classificação com rótulos descritos |

**Escopo deste ciclo:** classificação de intenções no atendimento de telefonia móvel (42 intenções em 13 domínios, mais "sem correspondência"), com 4.054 enunciados sintéticos anotados por três modelos generativos. As medições rodaram na OCI, em CPU e em GPU A10, com a configuração congelada antes do teste final.

## Resultados

Teste final com 1.744 exemplos, configuração congelada e três repetições. Detalhes em [reports/test](reports/test/README.md).

| Candidato | Acurácia (IC 95%) | Macro F1 | Decide sozinho com risco ≤ 2% | p95 em GPU A10 | Custo por mil decisões |
|---|---|---|---|---|---|
| **SemIf** | **87,2%** (85,0–89,4) | 0,889 | 62% (97% de acerto) | 187 ms | US$ 0,071 |
| **Rizzo Flow** | **85,4%** (83,2–87,6) | 0,877 | 47% (97% de acerto) | 181 ms | US$ 0,070 |
| GLiNER | 57,0% (52,6–61,5) | 0,580 | 13% | 32 ms | US$ 0,012 |
| Laya | 56,8% (52,9–60,5) | 0,590 | 10% | 23 ms | US$ 0,012 |

![Qualidade × latência em GPU](reports/test/chart-qualidade-latencia.svg)

- **Qualidade:** os modelos de 4B (SemIf e Rizzo Flow) acertam cerca de 86% e empatam estatisticamente entre si. Os encoders compactos ficam cerca de 30 p.p. abaixo.
- **Latência:** os encoders respondem em cerca de 20 ms e funcionam até em CPU. Os modelos de 4B ficam em cerca de 120 ms de mediana, mas passam do limite pré-registrado de p95 de 150 ms na A10.
- **Abstenção:** com probabilidades calibradas, o SemIf decide sozinho 62% dos casos com 97% de acerto e encaminha o resto para desambiguação. Nenhum candidato atinge a meta pré-registrada de 80% de cobertura com 2% de risco.
- **Principal fonte de erro grave:** quando a intenção correta não está entre as opções elegíveis, os modelos escolhem a opção mais próxima com alta confiança.

**Recomendação.** Usar o **SemIf** como modelo de decisão do orquestrador, com o **Rizzo Flow** como alternativa equivalente e mais leve em memória de GPU. Junto com isso:
- classificar contra o **catálogo completo** de intenções e aplicar a elegibilidade **depois**, de forma determinística;
- usar o **limiar calibrado** para pedir esclarecimento nos casos incertos;
- buscar uma GPU mais rápida que a A10 ou otimizações de inferência para cumprir o p95 de 150 ms.

Encoders compactos não servem como roteador principal neste domínio.

| Critério pré-registrado | SemIf | Rizzo Flow | GLiNER | Laya |
|---|---|---|---|---|
| H1 · macro F1 ≥ 0,80 | ✅ | ✅ | ❌ | ❌ |
| H2 · cobertura ≥ 80% com risco ≤ 2% | ❌ | ❌ | ❌ | ❌ |
| H3 · p95 ≤ 150 ms em GPU | ❌ | ❌ | ✅ | ✅ |

**Etapas e relatórios**

| Etapa | Conjunto | Destaque | Relatório |
|---|---|---|---|
| Piloto | 50 exemplos de dev | Execução validada em CPU e GPU; SemIf e Rizzo inviáveis em CPU | [reports/pilot](reports/pilot/README.md) |
| Desenvolvimento | 1.183 exemplos | Dois grupos de qualidade; o Laya cai com mais opções | [reports/dev](reports/dev/README.md) |
| Calibração | 1.127 exemplos | Temperatura e limiar por candidato; ECE do Laya de 0,33 para 0,08 | [reports/calibration](reports/calibration/README.md) |
| Teste final | 1.744 exemplos × 3 repetições | Resultados acima, com IC, cortes, custos e análise de erros | [reports/test](reports/test/README.md) |

**Limitações.** Os dados são sintéticos e os rótulos de referência vêm do consenso de três modelos generativos, não de pessoas. Não houve baseline LLM neste ciclo. A latência foi medida numa única GPU (A10) e com lote 1. O Rizzo Flow roda em Q8_0, enquanto os demais rodam na precisão nativa.

## Método

1. **Contrato único.** Todos os candidatos ficam atrás do mesmo contrato `POST /v1/systemone` (`jev-compat-v1`), com adaptadores que preservam a ordem e a descrição das opções. Testes de conformidade e de sanidade garantem que trocar de candidato não muda a requisição nem a resposta.
2. **Dados sintéticos controlados.** São 42 intenções e 5 categorias fora de escopo, com 7 perfis de escrita (curto, informal, com erros de digitação, regional, emocional, longo, indireto ou com várias intenções), escritos por dois modelos geradores. Os rótulos vêm de três anotadores generativos de outros fornecedores, em rodízio, com dois anotando de forma independente e o terceiro desempatando (kappa de 0,98 a 0,99). As opções de cada exemplo simulam um serviço de elegibilidade (4, 8, 12 ou 16 opções); em 10% dos exemplos, a intenção correta fica de fora.
3. **Partições disjuntas por lote de geração:** desenvolvimento (1.183), calibração (1.127) e teste (1.744), congeladas com SHA-256.
4. **Protocolo pré-registrado.** Critérios, limites e regras ficam em `config/benchmark.yaml` antes das medições: piloto → desenvolvimento → calibração (temperatura e limiar só na partição de calibração) → congelamento da configuração com hashes (tag `congelamento-d1-v1`) → teste final, que só abre se nada tiver mudado.
5. **Execução isolada e reprodutível na OCI.** Pesos e ambientes vêm de buckets, com SHA-256 conferido; a inferência roda sem acesso a fontes externas (sub-rede privada ou bloqueio no processo, com autoteste); cada medição repete três vezes. GPU `VM.GPU.A10.1`; CPU `VM.Standard.E4.Flex` com 8 OCPU.
6. **Análise:** IC 95% por bootstrap agrupado por lote, comparações pareadas, calibração (ECE, Brier), cobertura contra risco, cortes por perfil e número de opções, classificação dos erros e custo a preço público.

Detalhes em [docs/02 — desenho experimental](docs/02-desenho-experimental.md) e [docs/04 — decisões de projeto](docs/04-decisoes-de-projeto.md).

### Esclarecimento Metodológico

**O problema dos modelos de decisão:**   

- **Score alto com acurácia baixa** (modelo confiante demais): ele erra achando que acertou. É o erro perigoso.
- **Score baixo com acurácia alta** (modelo inseguro demais): ele acerta, mas não confia, e o sistema pede desambiguação sem necessidade.

**Etapa 1 — Calibração: deixar o score honesto**

Calibrar é ajustar o score para que **ele signifique o que diz**. Quando o modelo calibrado diz "90%", ele acerta cerca de 90% dessas vezes. Nessa etapa ainda não existe decisão nem risco.

- **Como foi feito:** com o histórico da partição de calibração (1.127 exemplos de acurácia conhecida), compara-se o score que cada modelo deu com o acerto real. Daí sai um único número de correção por modelo, a "temperatura":
  - **T > 1 achata o score** e corrige o excesso de confiança. Laya (T = 3,6): dizia ~95% de certeza e acertava ~55%.
  - **T < 1 estica o score** e corrige a falta de confiança. GLiNER (T = 0,8).
  - **T ≈ 1 quase não mexe.** SemIf e Rizzo (1,25 a 1,28), que já eram razoavelmente honestos.
- **Como se mede:** pelo ECE, a distância média entre a certeza que o modelo declara e o acerto real. No Laya, foi de 0,33 para 0,08.
- **O que não muda:** a calibração não troca a resposta do modelo, só o score. A ordem das opções é preservada, e por isso a acurácia é a mesma antes e depois.

**Etapa 2 — Limiar: aqui entra o fator de risco**

Com o score já honesto, escolhe-se a **régua**: acima dela o modelo decide sozinho, abaixo dela pede desambiguação. Esse é o cálculo de risco que você descreveu. Ele também usa a partição de calibração:
- para cada régua possível, conta-se quantos casos o modelo decidiria sozinho (cobertura) e quantos desses seriam erros com score alto (risco);
- escolhe-se a régua mais baixa que mantém o risco em até 2% do total.

**Por que a ordem importa**

Sem a etapa 1, a régua da etapa 2 não seria confiável. Num modelo confiante demais, a régua de 0,9 deixaria passar muito mais erros do que o esperado. A calibração faz com que "0,9" valha o mesmo em qualquer modelo e em qualquer dia, e só então a régua de risco funciona como previsto.

**Em uma frase:** a calibração alinha score e acurácia; o limiar transforma esse score confiável numa decisão com risco controlado. Os dois foram ajustados só com a partição de calibração e congelados antes do teste final, que confirmou o resultado: o risco ficou entre 1,4% e 1,9% para todos os candidatos.   

Portanto, **o modelo só decide sozinho quando está muito seguro, e esse "muito seguro" foi ajustado para que no máximo 2 em cada 100 mensagens acabem num erro que ninguém percebe.** Não é "incerteza abaixo de 2%". O 2% é o limite de **erros que passam batido**.

**A analogia: um atendente novato com um supervisor ao lado.**

A cada mensagem do cliente, o atendente pensa "acho que é sobre a fatura" e diz o quanto tem certeza, de 0% a 100%.

- **Se a certeza é alta** (acima de uma régua, por exemplo 91%), ele encaminha sozinho.
- **Se é baixa**, chama o supervisor, ou seja, o sistema pergunta ao cliente "você quer falar da fatura ou do plano?".

A pergunta do benchmark é: **onde colocar essa régua?**
- **Régua baixa:** o atendente resolve quase tudo sozinho, mas erra mais sem avisar ninguém.
- **Régua alta:** ele quase não erra, mas chama o supervisor o tempo todo.

**Como a régua foi escolhida**

Primeiro foi fixada a regra: **dentre todas as mensagens, no máximo 2% podem ser encaminhadas para o lugar errado com o modelo dizendo que tinha certeza.** Esse é o erro perigoso, porque o cliente cai no agente errado e ninguém percebe. Com essa regra fixa, a régua desce até o ponto mais baixo que ainda a respeita. Quanto mais baixa a régua, mais o modelo resolve sozinho.

Um detalhe importante: antes disso, os modelos foram **calibrados**. Um modelo que diz "90% de certeza" tem de acertar de fato cerca de 90% dessas vezes. Sem calibrar, alguns diziam 95% e acertavam bem menos (o Laya era o pior caso).

**O que deu, a cada 100 mensagens**

| Modelo | Resolve sozinho | Desses, acerta | Erros com "certeza" (o perigoso) | Pergunta de volta ao cliente |
|---|---|---|---|---|
| SemIf | 62 | ~60 (97%) | ~1,6 | 38 |
| Rizzo Flow | 47 | ~45 (97%) | ~1,5 | 53 |
| GLiNER | 13 | ~11 (85%) | ~1,9 | 87 |
| Laya | 10 | ~9 (87%) | ~1,4 | 90 |

**Como ler isso:**
- **SemIf:** de cada 100 mensagens, encaminha 62 sozinho e quase sempre acerta. As outras 38 viram uma pergunta de esclarecimento ao cliente. É o melhor equilíbrio.
- **Laya e GLiNER:** respeitam o limite de 2%, mas só porque quase nunca decidem sozinhos. Perguntariam de volta em ~90% das conversas, o que, na prática, torna o modelo inútil como roteador.

**Por que "nenhum atingiu a meta"**

A meta pré-registrada era resolver sozinho **pelo menos 80** de cada 100 mensagens, mantendo o erro perigoso em até 2. O melhor chegou a 62. Para o SemIf resolver 80 sozinho, o erro perigoso subiria para ~6 em cada 100.

**Em uma frase:** o SemIf consegue decidir sozinho em 6 de cada 10 conversas, com 97% de acerto. Nas outras 4, o orquestrador deve perguntar ao cliente antes de agir.   

## Detalhes do projeto

### Plano de tarefas

As 78 microtarefas, organizadas em 11 fases e com o andamento de cada uma, estão em [docs/03-plano-de-tarefas.md](docs/03-plano-de-tarefas.md). O resumo por fase é regenerado com `python tools/plan_progress.py`.

### Documentos

| Documento | Conteúdo |
|-----------|----------|
| [docs/01-contexto-arquitetural.md](docs/01-contexto-arquitetural.md) | Arquitetura de referência do orquestrador e onde o modelo de decisão atua |
| [docs/02-desenho-experimental.md](docs/02-desenho-experimental.md) | Tarefas de decisão, formato dos dados, partições, métricas e conjunto d1-v1 |
| [docs/03-plano-de-tarefas.md](docs/03-plano-de-tarefas.md) | Plano de 78 tarefas, com o andamento |
| [docs/04-decisoes-de-projeto.md](docs/04-decisoes-de-projeto.md) | Decisões de projeto (Q1–Q14) e os mecanismos que as aplicam |
| [docs/05-cenario-de-execucao.md](docs/05-cenario-de-execucao.md) | Cenário de execução: onde cada etapa roda, isolamento e fluxo dos dados |
| [docs/06-guia-de-anotacao.md](docs/06-guia-de-anotacao.md) | Guia de anotação, usado literalmente pelos anotadores |
| [reports/](reports/) | Relatórios do piloto, desenvolvimento, calibração e teste final, com dados, gráficos e análise |

### Reprodução

| Artefato | Onde |
|---|---|
| Manifesto de artefatos (origem, revisão, licença, SHA-256, tamanho) | [env/artifacts-manifest.json](env/artifacts-manifest.json) |
| Configuração pré-registrada, calibração e congelamento | [config/benchmark.yaml](config/benchmark.yaml), [config/calibration.json](config/calibration.json), [config/frozen.json](config/frozen.json) |
| Partições congeladas | [data/splits/](data/splits/) ([MANIFEST.json](data/splits/MANIFEST.json)) |
| Contrato e fixtures de conformidade | [contracts/jev/](contracts/jev/) |
| Predições, resumos de execução e análise | [reports/](reports/) |
| Logs de cada execução (stdout, stderr, `run.json`) e dados brutos da geração e anotação | Cópia local fora do Git (`runs/`, `data/raw/`) |
| Recriação do ambiente na OCI | `infra/oci/provision.py` → `env/acquire.py` → `infra/ds/build_env.sh`; remoção com `infra/oci/teardown.py` |

```bash
# testes locais do contrato, formato, servidor, isolamento, métricas, congelamento e dados sensíveis
python -m pytest -q

# avaliação de um candidato numa partição (job do OCI Data Science)
PYTHONPATH=infra/oci .venv/bin/python infra/ds/jobs.py run --name test-laya --entrypoint infra/ds/run_job.sh \
    --private --ocpus 8 --memory 64 --env DMB_CANDIDATE=laya DMB_MODE=evaluate DMB_SPLIT=test DMB_REP=1
PYTHONPATH=infra/oci:infra/ds .venv/bin/python infra/ds/gpu_queue.py evaluate semif rizzo_flow laya gliner \
    --env DMB_SPLIT=test DMB_REP=1

# coleta, análise e gráficos
PYTHONPATH=infra/oci .venv/bin/python infra/ds/collect.py --split test --examples 1744 --all-reps --dest reports/test
python -m analysis.report reports/test
python -m analysis.charts reports/test --kind test --label "teste final"
```

### Estrutura do repositório

```
config/             Configuração pré-registrada, calibração, congelamento e preços
contracts/jev/      Contrato jev-compat-v1: esquemas e fixtures de conformidade
dmb/                Código comum: contrato, formato canônico, servidor /v1/systemone, isolamento de rede, cliente de LLM
adapters/<modelo>/  Adaptadores JEV por candidato
harness/            Execução nos jobs, avaliação, sanidade, servidor e auditoria do bucket
datagen/            Pipeline sintético: geração, preparação, anotação por 3 LLMs, partições
data/               Taxonomia de intenções e partições congeladas
analysis/           Métricas, calibração, análise final e gráficos
env/                Aquisição de artefatos, manifesto e dependências por candidato
infra/oci/          Compartment, IAM, rede, buckets, réplica entre regiões, NAT
infra/ds/           Jobs do OCI Data Science: builds, execuções, fila de GPU, coleta
infra/vm/           Preparação e execução remota na VM de trabalho
models/             Metadados dos modelos (cards, configs, licenças); pesos ficam no Object Storage
reports/            Relatórios por etapa
tests/              Testes automatizados
tools/              Andamento do plano e congelamento da configuração
```

### Princípios

1. **Isolamento.** Na inferência, os modelos usam só artefatos com hash conhecido, sem acesso a fontes externas.
2. **Contrato único.** Todos os candidatos recebem a mesma requisição e devolvem o mesmo formato de resposta.
3. **Teste congelado.** Nada muda depois que o teste final é aberto, e o executor confere os hashes.
4. **Partições disjuntas.** Exemplos do mesmo lote de geração nunca aparecem em mais de uma partição.
5. **Reprodutibilidade.** Versões, seeds, hashes, configurações e comandos ficam versionados neste repositório.
