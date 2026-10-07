# 04 — Decisões de projeto (ex-questões em aberto)

Todas as questões foram resolvidas em 2026-10-07. O critério foi preferir a **abordagem automatizada e verificável**: regras determinísticas em código, gates que fazem o pipeline falhar, valores calculados a partir de medições e parâmetros pré-registrados em [config/benchmark.yaml](../config/benchmark.yaml). Ninguém precisa decidir nada caso a caso durante a execução. Os valores numéricos pré-registrados ficam congelados com hash no marco da tarefa 62.

## Resumo

| # | Questão | Decisão | Mecanismo automatizado |
|---|---------|---------|------------------------|
| Q1 | Contrato JEV | Esquema público do `POST /v1/systemone` (`state` + `questions` tipadas → `answers` + `usage`), congelado como `jev-compat-v1` | JSON Schema em `contracts/jev/schemas/` e testes de conformidade |
| Q2 | 20 opções incluem o fallback? | Sim, e o limite comum cai para **16**: até 15 opções de domínio + `sem_correspondencia` (revisado: o SemIf aceita só 16) | Validação de esquema (`maxProperties: 16`) e lint do dataset |
| Q3 | NAT × isolamento | Desassociar a rota NAT logo após a tarefa 16 | Gate de egresso: o pipeline só segue se a sonda de saída **falhar** |
| Q4 | Interfaces e licenças | Interfaces mapeadas por candidato (abaixo). Só licenças da allowlist | O script de aquisição lê a licença nos metadados do Hub e falha fora da allowlist |
| Q5 | Critérios de sucesso | SLO de latência fixo + não inferioridade relativa ao baseline | Avaliação automática dos critérios em `config/benchmark.yaml` |
| Q6 | Lote de produção | Escolhido por candidato: o maior lote com p95 dentro do SLO | Varredura de lotes no piloto |
| Q7 | Fonte dos dados | Reais anonimizados + sintéticos, com origem marcada | Geração sintética por template e LLM, anonimização automática, deduplicação |
| Q8 | Turnos no `state` | O maior N ∈ {0,1,2,4} que cabe no orçamento comum de tokens | Cálculo sobre a partição de desenvolvimento |
| Q9 | Baseline LLM | Incluído, fora do ranking principal | Adaptador JEV sobre o LLM Gateway |
| Q10 | Calibração | Temperature scaling por candidato × tarefa, só na partição de calibração | Ajuste por NLL e congelamento com hash |
| Q11 | Piloto em CPU | Mantido, com timeout. Inviabilidade declarada automaticamente | Regra p95 > timeout → "inviável em CPU" |
| Q12 | Tamanho do teste | ≥ 1.300 decisões D1 no teste final (análise de poder) | `analysis/sample_size.py`, com recálculo do MDE |
| Q14 | GPU | A10.1 em **sa-saopaulo-1**, um job por vez (limite da região). Sem VCN disponível lá: rede gerenciada + isolamento no processo (`DMB_ISOLATION=app`) | `infra/ds/gpu_queue.py`, `infra/oci/replicate.py`, autoteste `dmb.offline.self_test` |
| Q15 | Dados e anotação | 100% sintéticos; anotação por três modelos generativos em rodízio | `datagen/` (ver [02 §4](02-desenho-experimental.md#4-dados)) |
| Q13 | Centro de custo e orçamento | **Orçamento em aberto**: o uso está coberto por cota interna de engenharia. A estimativa de custo continua no relatório | A estimativa é calculada por script (tarefa 70) |

---

## Q14 — GPU em São Paulo (revisão de 2026-10-07)

- Em us-chicago-1 não há capacidade de A10, e A100 e V100 têm limite zero. Os jobs de GPU rodam em **sa-saopaulo-1, `VM.GPU.A10.1`**, com limite de **uma GPU por vez** (fila em `infra/ds/gpu_queue.py`).
- Pesos e ambientes são replicados do lado do servidor para `dmb-artefatos-gru` (`infra/oci/replicate.py`); os resultados vão para `dmb-resultados-gru`.
- O limite de VCNs da região está esgotado. Os jobs de GPU usam **rede gerenciada**, e o isolamento passa a valer no processo: variáveis offline, bloqueio de sockets fora do loopback e um **autoteste a cada execução** (`process_guard`). O gate de egresso registra que há saída de rede, mas não aborta (`DMB_ISOLATION=app`). É um desvio documentado em relação à tarefa 17. Se uma VCN for liberada em São Paulo, os jobs voltam para uma sub-rede privada.
- Todas as medições de GPU usam o mesmo shape e a mesma região. As de CPU continuam em us-chicago-1.

## Q15 — Dados sintéticos e anotação por LLMs (revisão de 2026-10-07)

- Substitui Q7: os dados são 100% sintéticos, incluindo fora de escopo e enunciados emocionais. Não há dados reais neste ciclo.
- A anotação humana (tarefas 30–31) é substituída por três modelos generativos de fornecedores distintos, em rodízio de papéis. O gerador nunca é um dos anotadores.
- Limitação para o relatório: os rótulos de referência refletem o consenso de LLMs, não de pessoas. A concordância entre anotadores (kappa por par) e com o rótulo de geração é reportada.

## Q1 — Contrato JEV `jev-compat-v1`

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
  "usage": {"input_tokens": 0, "output_tokens": 0}
}
```

**Erros:** `422` para requisição malformada, modelo desconhecido ou estado acima do contexto. `401` para autenticação, que não se aplica aos adaptadores locais. Comportamentos padronizados do benchmark (tarefa 40):

| Situação | Código | Contabilização |
|----------|--------|----------------|
| Requisição inválida | `422` | Erro do harness: falha o job |
| Estado acima do contexto, depois do truncamento comum | `422` | Erro de decisão (`error_type=context`) |
| Timeout (`timeout_ms` do cenário) | `504` | Erro de decisão (`error_type=timeout`) |
| Opção devolvida fora de `criteria` | `502` | Erro de decisão (`error_type=unknown_option`) |
| Modelo indisponível | `503` | Erro de execução: refaz até 3 vezes e depois falha o job |

**Mapeamento para os tipos internos (tarefas 38–39)**

- `choice` → D1, D2 e D5. A predição é `choice`; a distribuição é `probabilities`.
- `noul` → D3 e as perguntas por intenção de D4. P(sim) = `noul`.
- `score` → reservado. Não é usado no primeiro ciclo.
- **`confidence` não é calibrada** em nenhuma implementação. Por isso, todas as métricas de calibração e abstenção usam `max(probabilities)` (ou `max(noul, 1−noul)`) **depois** da calibração da tarefa 61. A `confidence` nativa é só registrada.
- Quando um candidato não expõe uma distribuição normalizada, o adaptador aplica softmax sobre os escores das opções e marca `metadata.probabilities_source = "normalized_scores"`.
- `output_tokens` deve ser sempre 0, porque não há geração. Um valor diferente de 0 reprova o teste de conformidade.

## Q2 — Limite de opções

O limite inclui `sem_correspondencia`. **Revisão (2026-10-07):** o código do SemIf (`semif_phase1.core.LETTERS = "A…P"`) aceita no máximo 16 opções. O Laya recomenda até ~20 e o Rizzo aceita 26. O limite comum passa a ser **16: até 15 opções de domínio + 1**. O dataset é validado por esquema. Um exemplo com mais de 16 opções reprova o lint e impede o congelamento (tarefa 35).

## Q3 — NAT e isolamento de rede

Sequência automatizada, em que cada passo falha o pipeline se não for cumprido:

1. **9 → 16:** a rota NAT existe só durante a aquisição.
2. **Fim da tarefa 16:** `infra/oci/nat.py off` remove a rota e o egresso `0.0.0.0/0` e bloqueia o NAT. O NAT só é criado ou ativado com `nat.py on`, quando for necessário.
3. **Gate de egresso (tarefas 17 e 19):** um job de sonda tenta resolver e abrir conexão com hosts públicos (Hugging Face Hub, PyPI). O gate passa só se **todas** as tentativas falharem e se o acesso ao Object Storage pelo Service Gateway funcionar.
4. **Toda execução de benchmark** roda o gate antes da inferência e grava o resultado no manifesto da execução.
5. **Tarefa 78:** o NAT Gateway é destruído, e o gate confirma que nenhum recurso do compartment tem rota de saída.

## Q4 — Interfaces e licenças dos candidatos

| Candidato | Licença | Interface usada pelo adaptador | Contexto declarado | Observação |
|-----------|---------|--------------------------------|--------------------|------------|
| Laya multilingual | Apache-2.0 | `laya.load(...).predict(state, questions)`, nativamente no formato JEV | 1.024 tokens (default), até 8.192 | Recomenda até ~20 opções. Vem descalibrado: a calibração da tarefa 61 é obrigatória |
| SemIf + Qwen3.5-4B | MIT (SemIf); Qwen: verificar no Hub | Modo `direct`: um forward pass lê os logits das opções declaradas | ~8k tokens | Revisão do Qwen fixada no manifesto |
| GLiNER2.5-multi-Decide | Apache-2.0 | `classify_text(text, {"<q>": {"labels": {opcao: descrição}}})` | Não declarado: medir | Não tem `noul`/`score` nativos. `noul` vira o rótulo binário `{true,false}`. As probabilidades são normalizadas a partir dos escores |
| Rizzo Flow 4B | Apache-2.0 (base); dados de treino com componentes CC-BY-SA/CC-BY | Prompt `spark-decisions-v3`, com leitura dos logits das letras de resposta | 2.048 tokens | **O formato de prompt é obrigatório**: o adaptador monta `spark-decisions-v3` a partir da serialização comum. Documentação só em inglês: o risco de idioma vai para o relatório |

Regras automatizadas:
- A **allowlist de licenças** (`Apache-2.0`, `MIT`) fica em `config/benchmark.yaml`. O script da tarefa 13 lê `cardData.license` de cada repositório no Hub. Licença ausente ou fora da lista falha a aquisição, até haver aprovação explícita registrada no manifesto.
- O **contexto efetivo** de cada candidato é medido por código: o mínimo entre `tokenizer.model_max_length`, `config.max_position_embeddings` e o limite declarado no adaptador. O resultado vai para o manifesto. Esse valor alimenta Q8.

## Q5 — Critérios de sucesso pré-registrados

Avaliados automaticamente pelo `analysis/` a partir de `config/benchmark.yaml`:

- **Desempenho (H3):** em GPU com lote 1, p95 ≤ **150 ms por decisão** e ≤ **300 ms por turno**. Em CPU os valores são só reportados.
- **Acurácia (H1):** em D1 e D2, **não inferioridade em relação ao baseline LLM** com margem de **3 p.p.**: o limite inferior do IC 95% (bootstrap pareado por conversa) da diferença precisa ser > −3 p.p. Sem baseline disponível, vale o critério absoluto: macro F1 ≥ 0,80.
- **Risco (H2):** no limiar escolhido na calibração, a taxa de **rota errada com confiança alta** precisa ser ≤ **2%**, com cobertura ≥ **80%**.

O critério relativo ao baseline dispensa um limiar absoluto arbitrário de acurácia, que dependeria da dificuldade do dataset.

## Q6 — Lote de produção

O piloto em GPU (tarefa 56) varre os lotes {1, 2, 4, 8, 16, 32}. O lote de produção de cada candidato é **o maior lote com p95 por decisão ≤ SLO**. O valor escolhido entra no manifesto e é congelado na tarefa 62. Lote 1 continua sendo o cenário principal. O lote de produção serve para reportar vazão e custo.

## Q7 — Fonte e preparação dos dados

- **Reais:** enunciados de conversas anonimizadas, se houver. **Sintéticos:** gerados a partir da taxonomia e dos templates adversariais (tarefa 27), com um LLM via gateway que **não** seja nenhum dos candidatos nem o baseline.
- **Anonimização automática (tarefa 25):** regras para CPF, CNPJ, telefone, e-mail, CEP, números de cartão e protocolo, além de NER de pessoas e lugares, substituindo os achados por marcadores tipados (`<CPF>`, `<NOME>`). Uma amostra aleatória de 5% passa por verificação humana. Qualquer vazamento encontrado obriga a reprocessar o lote inteiro.
- **Deduplicação:** MinHash/LSH para quase-duplicatas, dentro de cada fonte e entre fontes. Antes da partição, duplicatas recebem o mesmo `group_id`.
- O campo `metadata.source` ∈ {`real`, `synthetic`} existe em todos os exemplos. As métricas saem por fonte e no agregado.
- A anotação humana (tarefas 30–31) se mantém para todos os exemplos, inclusive os sintéticos. O rótulo de geração serve só como sugestão e é escondido dos anotadores.

## Q8 — Turnos no `state` e orçamento de tokens

1. **Orçamento comum** = o menor contexto efetivo medido entre os candidatos (Q4) − a reserva para a pergunta e as opções do maior exemplo.
2. **N** = o maior valor em {0, 1, 2, 4} em que ≥ 95% dos exemplos de desenvolvimento cabem no orçamento sem truncar o enunciado atual. A contagem usa o tokenizador **mais verboso** entre os candidatos.
3. A regra de truncamento (tarefa 53) remove primeiro os turnos mais antigos e nunca o enunciado atual. Se o enunciado sozinho estoura o orçamento, ele é truncado no fim e o exemplo recebe `truncated=true`.
4. Uma ablação com N ∈ {0, 1, 2, 4} roda **só no desenvolvimento** e serve só para o relatório. Ela não altera a configuração congelada.

## Q9 — Baseline LLM

- Um LLM generalista disponível via LLM Gateway ou serviço gerenciado na OCI, com a versão fixada no manifesto.
- Adaptador JEV próprio com saída restrita às opções. Quando houver logprobs, as probabilidades vêm deles. Quando não houver, a distribuição é one-hot com `probabilities_source="none"`, e o baseline fica fora das métricas de calibração.
- Tem a mesma serialização, o mesmo truncamento e os mesmos dados. Fica **fora do ranking principal** e serve de referência para H1 e para o custo.
- Por usar rede, é a **única exceção** ao isolamento. Roda num job separado, com egresso só para o endpoint do gateway, sem acesso aos artefatos dos candidatos.

## Q10 — Calibração

- **Temperature scaling** por candidato × tarefa de decisão: um único parâmetro, ajustado por minimização de NLL na partição de calibração. Para `noul`, o mesmo método é aplicado ao logit de P(sim).
- O calibrador só é aceito se reduzir o ECE na própria partição de calibração (validação cruzada em 5 dobras por `group_id`). Se não reduzir, fica a identidade (T = 1).
- Em seguida, os limiares de abstenção (tarefa 60) são escolhidos sobre as probabilidades calibradas, pelo critério de Q5: maximizar a cobertura com taxa de rota errada com confiança alta ≤ 2%.
- Os parâmetros T e os limiares são versionados e congelados com hash na tarefa 62.

## Q11 — Piloto em CPU

- Timeout de **10 s por decisão** em CPU.
- Regra automática: candidato com p95 > timeout ou com taxa de timeout > 5% no piloto recebe o status `inviavel_cpu` no manifesto e é excluído das rodadas finais em CPU. Os resultados em CPU dos demais são reportados como viabilidade, não como ranking.

## Q12 — Tamanho do conjunto de teste final

Análise de poder para a comparação pareada (teste de McNemar) entre dois candidatos em D1:

- Diferença mínima detectável d = 3 p.p., α = 0,05 (bilateral), poder = 0,80, proporção de discordância esperada p_d = 0,15:
  n ≈ (z₀.₉₇₅·√p_d + z₀.₈·√(p_d − d²))² / d² ≈ **1.300 decisões**.
- Correção de agrupamento: n_final = n × (1 + (m − 1)·ICC), em que m é o número médio de turnos por conversa e o ICC é estimado na partição de desenvolvimento. Antes de medir, usar ICC = 0,05.
- `analysis/sample_size.py` (a implementar) recalcula n com os valores observados. Se o teste congelado ficar abaixo do n necessário, o relatório troca a afirmação de significância pelo **MDE efetivo** do conjunto disponível.
- D2–D4 usam o que estiver disponível, com IC por bootstrap por conversa.

## Q13 — Centro de custo e orçamento

> **Revisão (2026-10-07):** o orçamento e os alertas (tarefas 3–4) ficam **em aberto**, porque o uso está coberto por cota interna de engenharia. A tag `centro_custo` não é aplicada por enquanto. O texto abaixo vale só se for necessário criar um orçamento depois.

- `centro_custo` é variável Terraform **obrigatória e sem default**. O `terraform plan` falha enquanto ela não for informada, o que impede criar recursos sem a tag.
- O valor do orçamento é calculado pelo script de estimativa, que multiplica as horas previstas por *shape* (piloto, dev, calibração, teste e repetições) pelo preço público da OCI e aplica um fator de contingência de 1,3. O resultado vai para `infra/oci/` como `budget_amount`. Os alertas de 50%, 80% e 100% (tarefa 4) são derivados desse valor.
