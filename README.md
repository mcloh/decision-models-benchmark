# Benchmark de modelos de decisão em PT-BR para roteamento em orquestradores multiagente

Benchmark reprodutível de modelos de decisão *open source*, do tipo "System 1" e semelhantes ao JEV (`POST /v1/systemone`), aplicados ao **roteamento e à orquestração de enunciados de usuário** (*user utterances*) num sistema multiagente com **A2A Gateway** e **MCP Gateway**.

O modelo de decisão é avaliado como um componente do **Agente Orquestrador**. A cada turno, ele toma decisões rápidas e estruturadas: identifica a intenção, escolhe o agente de destino, decide entre continuar, alternar ou retomar uma sessão e decide quando é preciso desambiguar. Essas decisões substituem ou complementam chamadas a LLMs generalistas.

## Objetivo

Comparar os candidatos em duas dimensões, nas mesmas condições:

- **Acurácia e calibração** das decisões de roteamento em PT-BR, incluindo casos ambíguos, adversariais e com várias intenções.
- **Desempenho operacional**: latência por turno (p50/p95/p99), vazão, memória, tempo de carga e custo por mil decisões, em CPU e GPU na OCI.

O resultado é um relatório técnico com uma recomendação. Todos os resultados podem ser reproduzidos a partir dos artefatos versionados.

## Participantes

| Candidato   | Artefato                                     |
|-------------|----------------------------------------------|
| Laya        | `convaiinnovations/laya-multilingual`        |
| SemIf       | `SemIf-OpenJev` com `Qwen/Qwen3.5-4B` (modo `direct`) |
| GLiNER      | `fastino/GLiNER2.5-multi-Decide` (`classify_text`) |
| Rizzo Flow  | `rizzoaiacademy/rizzo-flow` (4B)             |

Cada candidato é exposto por um adaptador local com o mesmo contrato JEV (`POST /v1/systemone`). Assim, o *harness* não sabe qual modelo está respondendo.

## Documentação

| Documento | Conteúdo |
|-----------|----------|
| [docs/01-contexto-arquitetural.md](docs/01-contexto-arquitetural.md) | Arquitetura de referência do orquestrador e onde o modelo de decisão atua |
| [docs/02-desenho-experimental.md](docs/02-desenho-experimental.md) | Tarefas de decisão, formato dos dados, partições, métricas e regras de isolamento |
| [docs/03-plano-de-tarefas.md](docs/03-plano-de-tarefas.md) | As 78 microtarefas organizadas em fases, com dependências e adaptações ao contexto de roteamento |
| [docs/04-questoes-em-aberto.md](docs/04-questoes-em-aberto.md) | Decisões de projeto (Q1–Q13) e os mecanismos automatizados que as aplicam |
| [config/benchmark.yaml](config/benchmark.yaml) | Parâmetros e critérios pré-registrados, congelados na tarefa 62 |

## Estrutura do repositório

```
config/            Configuração pré-registrada (benchmark.yaml)
infra/oci/          Compartment, tags, orçamento, IAM, VCN, buckets, Data Science (tarefas 1–10, 17, 78)
env/                Imagem de contêiner e manifesto de versões (11–12)
contracts/jev/      Contrato JEV jev-compat-v1: esquemas, mapeamento de tipos, fixtures de conformidade (36–41)
data/taxonomy/      Taxonomia de intenções/agentes e definição das tarefas de decisão (20–23)
data/raw/           Enunciados coletados e anonimizados — não versionar dados sensíveis (24–25)
data/annotated/     Anotações, adjudicação e referência (29–32)
data/splits/        Partições dev / calibração / teste congeladas (33–35)
adapters/<modelo>/  Adaptadores JEV locais por candidato (42–51)
harness/            Execução, controle de seeds/lotes/truncamento, coleta de medições (52–66)
analysis/           Métricas, cortes, análise de erros e gráficos (67–74)
reports/            Relatório técnico e anexos de reprodução (75–76)
```

## Princípios

1. **Isolamento de rede.** Na inferência, os modelos usam só artefatos locais com hash conhecido. Qualquer tentativa de download faz o job falhar.
2. **Contrato único.** Todos os candidatos recebem a mesma requisição JEV e devolvem o mesmo formato de resposta.
3. **Teste final congelado.** Prompts, opções, pesos e limiares não mudam depois que o conjunto de teste final é aberto.
4. **Partição por conversa.** Turnos de uma mesma conversa ou caso nunca aparecem em mais de uma partição.
5. **Reprodutibilidade.** Versões, seeds, hashes, configurações e comandos ficam registrados em manifestos anexados ao relatório.
