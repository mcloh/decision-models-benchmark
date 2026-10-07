# 02 — Desenho experimental

> **Escopo do primeiro ciclo (revisão de 2026-10-07).** Não há agentes implementados. Por isso o ciclo avalia só a **classificação de intenções (D1)** no domínio de **atendimento de telefonia móvel**, com a taxonomia `data/taxonomy/intents-v1.yaml` (42 intenções em 13 domínios). Pedidos fora de escopo, enunciados emocionais e casos com várias intenções entram como exemplos de D1, com rótulo `sem_correspondencia` ou a intenção principal. D2 a D5 ficam descritas abaixo para os próximos ciclos. Os dados são **100% sintéticos** e a anotação é feita por **três modelos generativos** (ver §4).

## 1. Hipóteses

- **H1 (acurácia).** Pelo menos um candidato atinge, em PT-BR, uma acurácia de roteamento (D1/D2) compatível com o uso no orquestrador. O critério é a não inferioridade em relação ao baseline LLM (margem de 3 p.p.); ver [04, Q5](04-questoes-em-aberto.md#q5--critérios-de-sucesso-pré-registrados).
- **H2 (calibração).** As probabilidades e a confiança devolvidas permitem uma política de abstenção (encaminhar para desambiguação) que melhora a acurácia seletiva sem derrubar demais a cobertura.
- **H3 (desempenho).** O candidato cabe no orçamento de latência por turno (p95 com lote 1) com um custo por mil decisões menor que o de uma chamada a um LLM generalista.

## 2. Tarefas de decisão

Cada tarefa tem **pergunta**, **opções com descrição** e **regra de decisão** (tarefa 21). No primeiro ciclo, cada questão tem **no máximo 16 opções**, incluindo `sem_correspondencia` (tarefas 22–23; limite do SemIf, ver Q2).

### D1 — Classificação de intenção

- **Pergunta:** "Qual intenção do usuário este enunciado expressa?"
- **Opções:** as intenções elegíveis do exemplo, de 1 a 15, mais `sem_correspondencia`. Cada opção tem uma descrição curta, do mesmo jeito que viria do catálogo de agentes ou intenções.
- **Regra:** escolher a intenção principal que o próximo agente precisa atender. Se nenhuma se aplica, escolher `sem_correspondencia`.

### D2 — Continuidade de sessão

- **Pergunta:** "Como o orquestrador deve tratar este turno, considerando o estado da conversa?"
- **Opções:** `continuar_agente_ativo`, `retomar_sessao:<agent_id>` (uma opção para cada sessão suspensa), `iniciar_novo_agente`, `desambiguar`.
- **Regra:** `continuar_agente_ativo` quando o enunciado dá sequência à tarefa em curso, mesmo que seja curto ("sim", "o segundo", "pode ser"). `retomar_sessao` quando o usuário volta a um assunto anterior. `iniciar_novo_agente` quando aparece uma intenção nova. `desambiguar` quando não dá para decidir com segurança.

### D3 — Necessidade de desambiguação

- **Pergunta:** "O enunciado tem informação suficiente para rotear sem perguntar ao usuário?"
- **Tipo:** `noul` (P(sim) = "dá para rotear sem perguntar").
- **Uso:** comparar a abstenção explícita (D3) com a abstenção derivada da confiança de D1 (tarefa 60).

### D4 — Várias intenções

- Aplica-se só a enunciados anotados com mais de uma intenção.
- Executa várias perguntas `noul` sobre o mesmo texto, uma por intenção candidata ("O enunciado pede X?"), na mesma requisição JEV (tarefa 65).
- Métrica: F1 por conjunto de intenções e custo total, que soma as latências.

### D5 — Guardrail de entrada *(opcional)*

- Opções: `no_escopo`, `fora_do_escopo`, `requer_bloqueio`. Só entra se houver dados anotados suficientes.

## 3. Formato canônico de entrada (tarefa 36)

```json
{
  "id": "conv-000123-t04-D2",
  "group_id": "conv-000123",
  "task": "D2",
  "state": {
    "active_agent": "agente_a",
    "suspended_sessions": ["agente_b"],
    "recent_turns": [
      {"role": "user", "text": "..."},
      {"role": "agent", "agent_id": "agente_a", "text": "..."}
    ],
    "eligible_intents": ["intencao_1", "intencao_2"]
  },
  "utterance": "...",
  "question": "Como o orquestrador deve tratar este turno?",
  "question_type": "choice",
  "options": {
    "continuar_agente_ativo": "...",
    "retomar_sessao:agente_b": "...",
    "iniciar_novo_agente": "...",
    "desambiguar": "..."
  },
  "gold_label": "retomar_sessao:agente_b",
  "metadata": {
    "taxonomy_version": "v0.1",
    "domain": "...",
    "length_bucket": "curto",
    "ambiguity": "media",
    "turn_index": 4,
    "adversarial": ["abreviacao"],
    "n_options": 4,
    "n_tokens": {"laya": 0, "semif": 0, "gliner": 0, "rizzo_flow": 0}
  }
}
```

**Conversão para JEV.** `question` vira `questions.<task>.instructions` e `options` vira `criteria` (contrato `jev-compat-v1`, em [contracts/jev/schemas/](../contracts/jev/schemas/)). O `state` enviado é sempre o **texto serializado** descrito abaixo, nunca o objeto estruturado.

**Serialização do estado.** Alguns candidatos aceitam só texto, e não `state` estruturado. Por isso, uma **única regra de serialização** de `state` + `utterance` em texto vale para todos os adaptadores (um bloco "Contexto:" com o agente ativo, as sessões suspensas e os N últimos turnos, seguido de "Mensagem:"; N calculado como em [04, Q8](04-questoes-em-aberto.md#q8--turnos-no-state-e-orçamento-de-tokens)). A regra é versionada junto com a política de truncamento (tarefa 53). Um adaptador não pode usar informação de `state` que não esteja nessa serialização.

## 4. Dados

**Primeiro ciclo: pipeline sintético (`datagen/`), executado na VM.**

| Etapa | Implementação | Tarefas |
|-------|---------------|---------|
| Geração | `datagen.generate`: 42 intenções × 7 perfis + 5 categorias fora de escopo × 9 lotes; 12 enunciados por lote. Geradores alternados `meta.llama-4-maverick` e `cohere.command-a` (fornecedores distintos dos anotadores). Perfis: curto/neutro, informal/abreviado, erros de digitação, regionalismo, emocional, longo com contexto, indireto ou com várias intenções | 24, 27 |
| Preparação | `datagen.prepare`: mascaramento de dados pessoais (CPF, CNPJ, cartão, telefone, e-mail, CEP), deduplicação exata e aproximada (Jaccard ≥ 0,85 em 5-gramas), limites de comprimento | 25, 28 |
| Anotação | `datagen.annotate`: três modelos (`openai.gpt-5.5`, `google.gemini-2.5-pro`, `xai.grok-4.3`) em rodízio por lote; dois anotam de forma independente, sem ver o rótulo de geração, e o terceiro desempata. Três rótulos distintos → exemplo excluído. Instruções: [06-guia-de-anotacao.md](06-guia-de-anotacao.md) | 29–32 |
| Montagem | `datagen.build`: partição por lote de geração (3/2/2 lotes por intenção para teste/calibração/dev), conjuntos de 4, 8, 12 ou 16 opções simulando a elegibilidade (10% sem a intenção correta → `sem_correspondencia`), lint e congelamento com SHA-256 em `dmb-entrada` e `dmb-logs-imutaveis` | 33–36 |

Itens abaixo descrevem o desenho geral (válido também para dados reais em ciclos futuros).


- **Unidade de amostragem:** conversa (`group_id`). Cada turno anotado gera um ou mais exemplos (um por tarefa de decisão).
- **Fontes:** enunciados representativos do domínio de destino, anonimizados (tarefas 24–25). Se houver dados sintéticos, eles ficam identificados em `metadata` e são reportados em separado.
- **Estratificação (tarefa 26):** domínio, comprimento, ambiguidade, classe esperada, posição do turno e presença de agente ativo ou de sessões suspensas.
- **Adversariais (tarefa 27):** abreviações, erros de ortografia, regionalismos, enunciados muito curtos e dependentes de contexto ("sim", "o outro"), várias intenções, troca de assunto no meio da conversa, retorno a um assunto anterior e pedidos fora de escopo.
- **Anotação (tarefas 29–32):** dois anotadores independentes e um terceiro para adjudicação. Para cada exemplo se registram o rótulo, a justificativa e a versão da taxonomia. A concordância (kappa de Cohen ou alfa de Krippendorff) vai para o relatório.
- **Partições (tarefas 33–35):** desenvolvimento, calibração e teste final, separadas por `group_id`. O teste final é congelado (hash registrado) antes de qualquer ajuste.

## 5. Protocolo de execução

| Etapa | Partição | O que pode mudar | Tarefas |
|-------|----------|------------------|---------|
| Conformidade e sanidade | fixtures | adaptadores | 41, 49–51 |
| Piloto CPU/GPU (50 ex.) | dev | só parâmetros operacionais | 55–58 |
| Desenvolvimento | dev | nada além do operacional; sem calibração | 59 |
| Calibração | calibração | limiares de confiança, regra de abstenção, calibradores por candidato | 60–61 |
| **Congelamento** | — | **nada** daqui em diante | 62 |
| Teste final | teste | — | 63–66 |

- Seeds, ordem dos exemplos, lote, precisão numérica (fp32, bf16 ou fp16 por candidato, registrada) e limite de tokens fixos por execução (tarefa 52).
- As medições de desempenho são feitas depois do aquecimento, com no mínimo três execuções independentes (tarefa 66).
- Cenários de execução: CPU com lote 1, GPU com lote 1 e GPU com lote de produção (escolhido automaticamente, ver Q6). O lote 1 representa o caminho síncrono do orquestrador; o lote maior mede a vazão.

## 6. Métricas

**Qualidade (tarefas 67–68)**
- Accuracy, macro F1, precision e recall por classe, matriz de confusão.
- Taxa de **rota errada com confiança alta** (erro que não seria desambiguado): é a métrica de maior impacto operacional.
- Brier score, ECE, curva cobertura × acurácia seletiva e AURC, calculados sobre `max(probabilities)` calibrado. A `confidence` nativa do JEV não é calibrada e só é registrada.
- D4: F1 por conjunto de intenções.

**Desempenho (tarefas 69–70)**
- Latência p50, p95 e p99 por decisão e por turno (soma das decisões do turno).
- Vazão, uso de GPU, RAM, VRAM, tempo de carga, tempo de aquecimento e armazenamento dos artefatos.
- Custo estimado por mil decisões em cada cenário, a partir do preço do *shape* OCI e da vazão medida.

**Cortes (tarefa 71):** tarefa de decisão, número de opções, comprimento, ambiguidade, posição do turno, com ou sem agente ativo e categoria adversarial.

**Análise de erros (tarefas 72–73):** taxonomia, contexto insuficiente, ambiguidade, linguagem, truncamento, instrução ou desempenho do modelo.

## 7. Ameaças à validade

- **Vantagem de formato.** Cada modelo pode ter sido treinado com um estilo de prompt diferente. Por isso há um contrato único e uma serialização única, e os desvios ficam documentados por adaptador.
- **Vazamento entre partições.** É controlado pela partição por `group_id` e pelo congelamento com hash.
- **Truncamento desigual.** Todos usam a mesma política, baseada no menor contexto efetivo, e a contagem de tokens de cada entrada é registrada.
- **Representatividade.** Dados sintéticos e reais são reportados em separado.
- **Elegibilidade simulada.** Em produção, o conjunto de opções vem de um serviço. Aqui ele é fixado por exemplo.
