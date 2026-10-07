# 04 — Decisões de projeto

As decisões do benchmark seguem um mesmo critério: preferir a **abordagem automatizada e verificável**. Isso significa regras determinísticas em código, gates que fazem o pipeline falhar, valores calculados a partir de medições e parâmetros pré-registrados em [config/benchmark.yaml](../config/benchmark.yaml). Nenhuma decisão é tomada caso a caso durante a execução, e os valores pré-registrados são congelados com hash na tarefa 62.

## Resumo

| # | Tema | Decisão | Mecanismo |
|---|------|---------|-----------|
| Q1 | Contrato | `POST /v1/systemone` público (`state` + `questions` tipadas → `answers` + `usage`), congelado como `jev-compat-v1` | JSON Schema em `contracts/jev/schemas/` e testes de conformidade |
| Q2 | Número de opções | Até **16** por pergunta: 15 de domínio + `sem_correspondencia` | Validação de esquema e lint do conjunto de dados |
| Q3 | Isolamento de rede | Aquisição fora da rede dos jobs; medições sem acesso a fontes externas | Gate de egresso, bloqueio no processo e verificação por SHA-256 |
| Q4 | Interfaces e licenças | Uma interface por candidato (abaixo); só licenças Apache-2.0 ou MIT | A aquisição lê a licença no Hub e falha fora da lista permitida |
| Q5 | Critérios de sucesso | Limite de latência fixo e não inferioridade em relação ao baseline | Avaliação automática a partir de `config/benchmark.yaml` |
| Q6 | Lote de produção | Por candidato: o maior lote com p95 dentro do limite | Varredura de lotes |
| Q7 | Dados e anotação | 100% sintéticos; anotação por três modelos generativos em rodízio | `datagen/` ([02 §4](02-desenho-experimental.md#4-dados)) |
| Q8 | Contexto no `state` | Orçamento comum de tokens; D1 usa só o enunciado atual | `dmb.canonical.fit_state` |
| Q9 | Baseline LLM | Incluído como referência, fora do ranking principal | Adaptador no mesmo contrato |
| Q10 | Calibração | Temperature scaling por candidato e tarefa, só na partição de calibração | Ajuste por NLL e congelamento com hash |
| Q11 | CPU | Medida com timeout; inviabilidade declarada por regra | p95 > timeout → `inviavel_cpu` |
| Q12 | Tamanho do teste | ≥ 1.300 decisões D1 (análise de poder) | Recalculado na análise |
| Q13 | Custos | Sem orçamento provisionado neste ciclo; custo estimado no relatório | Estimativa por cenário (tarefa 70) |
| Q14 | Cenário de GPU | `VM.GPU.A10.1` em sa-saopaulo-1, execuções em fila | `infra/ds/gpu_queue.py` e réplica dos artefatos |

---

## Q1 — Contrato `jev-compat-v1`

Base: a forma pública do `POST /v1/systemone`, a mesma reproduzida pelas implementações abertas (OpenJev/SemIf).

**Requisição**

```json
{
  "model": "<model_id>",
  "state": "<texto> | <objeto JSON>",
  "questions": {
    "<nome>": {"type": "choice", "instructions": "...", "criteria": {"<opcao>": "<descrição>"}},
    "<nome>": {"type": "noul",   "instructions": "...", "criteria": {"true": "...", "false": "..."}},
    "<nome>": {"type": "score",  "instructions": "...", "criteria": ["<nível 0>", "<nível 1>", "..."]}
  }
}
```

**Resposta**

```json
{
  "model": "<model_id>",
  "answers": {
    "<nome>": {"type": "choice", "choice": "<opcao>", "confidence": 0.0, "probabilities": {"<opcao>": 0.0}},
    "<nome>": {"type": "noul", "noul": 0.0},
    "<nome>": {"type": "score", "score": 0.0, "confidence": 0.0,
               "probabilities": {"0": 0.0}, "legend": {"0": "<nível 0>"}}
  },
  "usage": {"input_tokens": 0, "output_tokens": 0},
  "metadata": {"latency_ms": 0.0, "model_id": "...", "run_id": "...", "adapter_version": "...",
               "diagnostics": {}}
}
```

**Comportamentos padronizados (tarefa 40)**

| Situação | Código | Contabilização |
|----------|--------|----------------|
| Requisição inválida | `422` | Erro do harness: o job falha |
| Estado acima do contexto, depois do truncamento comum | `422` | Erro de decisão (`error_type=context`) |
| Timeout | `504` | Erro de decisão (`error_type=timeout`) |
| Opção devolvida fora de `criteria` ou com a ordem alterada | `502` | Erro de decisão (`error_type=unknown_option`) |
| Modelo indisponível | `503` | Erro de execução |

**Mapeamento dos tipos (tarefas 38–39)**

- `choice` → D1, D2 e D5. A predição é `choice`; a distribuição é `probabilities`.
- `noul` → D3 e as perguntas por intenção de D4. P(sim) = `noul`.
- `score` → reservado para ciclos futuros.
- **`confidence` não é calibrada** em nenhum candidato. As métricas de calibração e abstenção usam `max(probabilities)` depois da calibração da tarefa 61; a `confidence` nativa é só registrada.
- Todas as distribuições recebem um piso numérico comum (1e-6) e são renormalizadas, preservando a ordem das opções.
- `output_tokens` é sempre 0, porque não há geração.
- `metadata.diagnostics` traz avisos do próprio modelo, por exemplo opções truncadas pelo orçamento interno do Laya.

## Q2 — Número de opções

O limite comum é de **16 opções**, incluindo `sem_correspondencia`. Esse é o máximo aceito pela interface de todos os candidatos: o SemIf usa as letras A–P, o Laya recomenda até cerca de 20 e o Rizzo aceita 26. Um exemplo com mais de 16 opções reprova o lint e impede o congelamento.

## Q3 — Isolamento de rede

- **Aquisição.** Pesos, tokenizadores, código-fonte e runtimes são obtidos fora da rede dos jobs e publicados no bucket de artefatos, com SHA-256 no manifesto. Os ambientes dos candidatos são montados por jobs de build e também publicados no bucket.
- **Medições em CPU.** Rodam numa sub-rede privada que só alcança os serviços OCI pela Service Gateway. O gate de egresso tenta abrir conexão com hosts públicos (Hugging Face Hub, PyPI, GitHub) e só aprova se todas as tentativas falharem.
- **Medições em GPU.** Rodam na rede gerenciada do serviço, com o isolamento garantido no processo (ver Q14).
- **Em todas as medições:** variáveis offline, bloqueio de sockets fora do loopback e um autoteste registrado em cada resultado (`process_guard`).
- `infra/oci/nat.py` permite abrir uma saída temporária por NAT, caso alguma aquisição futura precise ser feita de dentro da VCN.

## Q4 — Interfaces e licenças dos candidatos

| Candidato | Licença | Interface usada pelo adaptador | Contexto | Observação |
|-----------|---------|--------------------------------|----------|------------|
| Laya multilingual | Apache-2.0 | `laya.load(...).predict(state, questions)`, nativo no formato JEV | 1.024 tokens (até 8.192) | Pergunta e opções dividem um orçamento interno de cabeçalho (`head_max_len`). As probabilidades vêm descalibradas e arredondadas em 4 casas |
| SemIf + Qwen3.5-4B | MIT (SemIf), Apache-2.0 (Qwen) | Modo `direct`: um forward pass lê os logits das opções declaradas | 8.192 tokens | Revisão do Qwen fixada no manifesto; bf16 |
| GLiNER2.5-multi-Decide | Apache-2.0 | `classify_text` com rótulos descritos; distribuição completa pelo softmax do próprio modelo (`multi_label` com `class_act="softmax"` e limiar 0) | 4.096 tokens | A pergunta entra como prefixo do texto, porque `classify_text` não tem campo de instrução |
| Rizzo Flow 4B | Apache-2.0 (base); dados de treino com componentes CC-BY-SA/CC-BY | Prompts `spark-decisions-v3` e leitura dos logits das letras de resposta, GGUF Q8_0 no llama.cpp | 2.048 tokens | Formato de prompt obrigatório; documentação só em inglês |

- A **lista de licenças permitidas** fica em `config/benchmark.yaml`. A aquisição lê `cardData.license` no Hub e falha fora da lista.
- O **contexto efetivo** de cada candidato fica registrado no adaptador e no resumo de cada execução.

## Q5 — Critérios de sucesso pré-registrados

- **Desempenho (H3):** em GPU com lote 1, p95 ≤ **150 ms por decisão**. Em CPU, os valores são reportados como viabilidade.
- **Acurácia (H1):** **não inferioridade em relação ao baseline LLM**, com margem de **3 p.p.**: o limite inferior do IC 95% (bootstrap pareado por grupo) da diferença precisa ser > −3 p.p. Sem baseline, vale o critério absoluto de macro F1 ≥ 0,80.
- **Risco (H2):** no limiar escolhido na calibração, a taxa de **rota errada com confiança alta** precisa ser ≤ **2%**, com cobertura ≥ **80%**.

## Q6 — Lote de produção

A varredura de lotes {1, 2, 4, 8, 16, 32} em GPU define, por candidato, o maior lote com p95 por decisão dentro do limite. Lote 1 é o cenário principal, porque representa o caminho síncrono do orquestrador. O lote de produção serve para reportar vazão e custo.

## Q7 — Dados sintéticos e anotação por modelos generativos

- **Dados 100% sintéticos** no domínio de atendimento de telefonia móvel, incluindo pedidos fora de escopo e enunciados emocionais. São gerados por modelos de fornecedores diferentes dos anotadores (`meta.llama-4-maverick` e `cohere.command-a`).
- **Preparação:** mascaramento de dados pessoais (CPF, CNPJ, cartão, telefone, e-mail, CEP), deduplicação exata e aproximada, e limites de comprimento.
- **Anotação:** três modelos generativos de fornecedores distintos (`openai.gpt-5.5`, `google.gemini-2.5-pro` e `xai.grok-4.3`), em rodízio. Por lote, dois anotam de forma independente, sem ver o rótulo de geração, e o terceiro desempata. Três rótulos distintos excluem o exemplo.
- **Partição** por lote de geração (`group_id`), para que paráfrases do mesmo lote nunca fiquem em partições diferentes.
- **Limitação:** os rótulos de referência refletem o consenso de modelos generativos, não de pessoas. O relatório traz a concordância entre anotadores (kappa por par) e com o rótulo de geração.

## Q8 — Contexto no `state` e orçamento de tokens

- Todos os candidatos recebem o mesmo texto serializado (`state-text-v1`), com orçamento de **512 tokens** para o estado.
- A regra de truncamento remove primeiro os turnos mais antigos e só corta o fim do enunciado se ele sozinho estourar o orçamento. O exemplo recebe `truncated=true`.
- Em D1 não há histórico (`n_turns = 0`). O maior estado do conjunto d1-v1 tem menos de 120 tokens em qualquer tokenizador, então não há truncamento.
- Para tarefas com histórico (D2–D4), N ∈ {0, 1, 2, 4} é definido como o maior valor em que ≥ 95% dos exemplos de desenvolvimento cabem no orçamento.

## Q9 — Baseline LLM

- Um LLM generalista do OCI Generative AI, com a versão fixada no manifesto e adaptador no mesmo contrato, com saída restrita às opções.
- Quando há logprobs, as probabilidades vêm deles. Sem logprobs, a distribuição é one-hot e o baseline fica fora das métricas de calibração.
- Usa a mesma serialização e os mesmos dados. Serve de referência para H1 e para custo, fora do ranking principal.

## Q10 — Calibração

- **Temperature scaling** por candidato e tarefa: um único parâmetro, ajustado por minimização de NLL na partição de calibração.
- O calibrador só é aceito se reduzir o ECE em validação cruzada de 5 dobras por `group_id`. Caso contrário, mantém-se T = 1.
- Os limiares de abstenção são escolhidos sobre as probabilidades calibradas, maximizando a cobertura com taxa de rota errada com confiança alta ≤ 2%.
- Os parâmetros T e os limiares são versionados e congelados com hash na tarefa 62.

## Q11 — CPU

- Timeout de **10 s por decisão**.
- Um candidato com p95 acima do timeout, ou com taxa de timeout acima de 5%, recebe `inviavel_cpu` e fica fora das rodadas finais em CPU. Os resultados em CPU são reportados como viabilidade, não como ranking.

## Q12 — Tamanho do conjunto de teste final

- Análise de poder para a comparação pareada (McNemar) entre dois candidatos em D1: diferença mínima detectável de 3 p.p., α = 0,05, poder de 0,80, discordância esperada de 0,15. Isso dá n ≈ **1.300 decisões**.
- O teste d1-v1 tem **1.744 decisões**.
- A análise recalcula o efeito mínimo detectável com a discordância observada e com a correção de agrupamento por `group_id`.

## Q13 — Custos

O uso deste ciclo está coberto por cota interna de engenharia, então não há orçamento nem alertas provisionados. O relatório traz o **custo estimado por mil decisões** em cada cenário (tarefa 70), calculado a partir do preço público do shape e da vazão medida.

## Q14 — Cenário de GPU

- Todas as medições de GPU usam o mesmo shape e a mesma região: `VM.GPU.A10.1` em **sa-saopaulo-1**, com execuções em fila (`infra/ds/gpu_queue.py`).
- Pesos e ambientes são replicados do lado do servidor para `dmb-artefatos-gru` (`infra/oci/replicate.py`); os resultados ficam em `dmb-resultados-gru`.
- Os jobs usam a rede gerenciada do serviço, e o isolamento é feito no processo (`DMB_ISOLATION=app`): variáveis offline, bloqueio de sockets e autoteste (`process_guard`) registrado em cada resultado.
- As medições em CPU usam a sub-rede privada em us-chicago-1. CPU e GPU são reportadas em separado.
