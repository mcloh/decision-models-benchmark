# Resultados — partição `calibration`

Gerado por `infra/ds/collect.py`. Lote 1; latências sem os exemplos de aquecimento; probabilidades sem calibração.

<!-- TABELA:INICIO -->
| Candidato | Disp. | Precisão | n | Acurácia | Macro F1 | ECE (bruto) | p50 ms | p95 ms | p99 ms | Carga s | RAM pico MiB | GPU pico MiB | Erros | Truncados |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gliner | cpu | float32 | 1127 | 54.5% | 54.2% | 0.077 | 257.1 | 493.9 | 601.4 | 20.1 | 3240 | — | 0 | 0 |
| gliner | cuda | float32 | 1127 | 54.5% | 54.2% | 0.077 | 18.7 | 31.6 | 33.5 | 21.6 | 3252 | 1783 | 0 | 0 |
| laya | cpu | float32 | 1127 | 50.5% | 52.9% | 0.330 | 162.6 | 209.8 | 269.9 | 9.3 | 2681 | — | 0 | 0 |
| laya | cuda | float32 | 1127 | 50.8% | 53.3% | 0.326 | 21.5 | 22.8 | 24.0 | 9.9 | 2787 | 1811 | 0 | 0 |
| rizzo_flow | cuda | gguf-q8_0 | 1127 | 83.3% | 86.5% | 0.058 | 112.3 | 179.3 | 183.5 | 5.3 | 4528 | 5115 | 0 | 0 |
| semif | cuda | bfloat16 | 1127 | 85.8% | 88.1% | 0.055 | 117.2 | 184.2 | 186.8 | 7.9 | 9030 | 8513 | 0 | 0 |
<!-- TABELA:FIM -->
