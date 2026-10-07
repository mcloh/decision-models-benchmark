# 06 — Guia de anotação (tarefa 29)

Este guia é usado **literalmente** como instrução dos anotadores. São três modelos generativos de fornecedores distintos, em rodízio entre os papéis de anotador e de desempate (ver [02-desenho-experimental.md §4](02-desenho-experimental.md#4-dados)). As intenções e suas descrições estão em `data/taxonomy/intents-v1.yaml`.

<!-- GUIA:INICIO -->
## Tarefa

Você recebe mensagens que clientes de uma operadora de telefonia móvel enviaram ao canal de atendimento digital (chat ou aplicativo de mensagens). Para cada mensagem, escolha **uma intenção principal** da taxonomia: o que o cliente quer que o atendimento faça **agora**. Se nenhuma intenção se aplicar, use `sem_correspondencia`.

## Regras

1. **Intenção principal = ação pedida.** Rotule pelo que o cliente quer que aconteça, não pelo assunto mencionado de passagem.
2. **Tom não muda a intenção.** Irritação, ansiedade, ironia ou xingamentos não alteram o rótulo. "Que absurdo, cobraram um serviço que eu nunca pedi, quero meu dinheiro de volta" → `conta_contestacao`.
3. **Desabafo sem pedido** (só reclamação emocional, ofensa ou xingamento sem ação identificável) → `sem_correspondencia`.
4. **Reclamação do próprio atendimento** (demora, protocolo sem solução, pedido de ouvidoria) → `reclamacao_atendimento`. Pedido explícito para falar com uma pessoa → `atendimento_humano`, mesmo que o motivo seja citado.
5. **Várias intenções na mesma mensagem:** escolha a que o cliente pede primeiro ou com mais ênfase e liste as demais em `secundarias`.
6. **Saudação + pedido:** ignore a saudação. Saudação, agradecimento ou teste isolado → `sem_correspondencia`.
7. **Fora do domínio** (outro tipo de empresa, assuntos gerais, texto ininteligível) → `sem_correspondencia`.
8. **Mensagem vaga demais** para identificar qualquer intenção ("preciso resolver um problema", "me ajuda") → `sem_correspondencia` com `ambiguidade` alta.

## Pares difíceis

| Situação | Rótulo |
|----------|--------|
| Diz que a cobrança é indevida e/ou pede estorno | `conta_contestacao` |
| Só quer entender a fatura ou o aumento | `conta_explicacao` |
| Cobrança indevida de uso no exterior | `roaming_cobranca` |
| Quer cancelar um serviço adicional ou assinatura (mesmo citando a cobrança) | `vas_cancelamento` |
| Linha bloqueada por falta de pagamento e quer reativar | `negociacao_religacao` |
| Já pagou e quer confirmar se o pagamento caiu | `conta_pagamento_confirmacao` |
| Quer negociar ou parcelar o que está atrasado | `negociacao_divida` |
| Problema só com internet móvel (dados) | `internet_problema_conexao` |
| Sem sinal ou sem conseguir ligar ou receber chamadas e SMS | `suporte_sem_sinal` |
| Recarga paga que não caiu | `recarga_nao_creditada` |
| Bônus prometido que não veio | `bonus_nao_recebido` |
| Quer pagar menos para continuar ou ameaça sair pedindo condição melhor | `desconto_retencao` |
| Quer encerrar a linha sem pedir condição | `cancelamento_linha` |
| Levar ou trazer o número de outra operadora | `portabilidade` |
| Perdeu ou teve o aparelho roubado | `seguranca_perda_roubo` |
| Linha clonada, golpe ou contratação que não reconhece | `seguranca_fraude` |

## Resposta

Para cada mensagem, devolva:
- `rotulo`: um id da taxonomia ou `sem_correspondencia`;
- `secundarias`: lista (possivelmente vazia) de outros ids presentes;
- `ambiguidade`: `baixa`, `media` ou `alta`;
- `justificativa`: uma frase curta.
<!-- GUIA:FIM -->
