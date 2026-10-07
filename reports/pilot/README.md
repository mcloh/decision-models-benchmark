# Resultados — partição `dev`, 50 exemplos

Gerado por `infra/ds/collect.py` a partir dos buckets de resultados. CPU: us-chicago-1 (`VM.Standard.E4.Flex`, 8 OCPU, sub-rede privada). GPU: sa-saopaulo-1 (`VM.GPU.A10.1`). Lote 1; latências excluem os exemplos de aquecimento. Probabilidades ainda sem calibração.

| Candidato | Disp. | Precisão | n | Acurácia | Macro F1 | ECE (bruto) | p50 ms | p95 ms | p99 ms | Carga s | RAM pico MiB | GPU pico MiB | Erros | Truncados |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gliner | cpu | float32 | 50 | 48.0% | 43.9% | 0.198 | 244.0 | 481.0 | 511.6 | 21.0 | 3257 | — | 0 | 0 |
| gliner | cuda | float32 | 50 | 48.0% | 43.9% | 0.198 | 18.1 | 31.0 | 32.7 | 21.5 | 3256 | 1681 | 0 | 0 |
| laya | cpu | float32 | 50 | 66.0% | 63.5% | 0.252 | 161.3 | 200.5 | 220.7 | 9.3 | 2673 | — | 0 | 0 |
| laya | cuda | float32 | 50 | 66.0% | 63.5% | 0.266 | 22.0 | 23.0 | 23.2 | 9.1 | 2773 | 1811 | 0 | 0 |
| rizzo_flow | cpu | gguf-q8_0 | 50 | 86.0% | 87.5% | 0.095 | 12734.4 | 18693.6 | 19293.6 | 4.0 | 4936 | — | 0 | 0 |
| rizzo_flow | cuda | gguf-q8_0 | 50 | 82.0% | 84.3% | 0.103 | 108.1 | 174.7 | 182.5 | 5.3 | 4527 | 5107 | 0 | 0 |
| semif | cpu | bfloat16 | 50 | 92.0% | 93.9% | 0.079 | 30633.4 | 47585.7 | 49344.0 | 6.3 | 9137 | — | 0 | 0 |
| semif | cuda | bfloat16 | 50 | 92.0% | 93.9% | 0.114 | 113.8 | 181.3 | 183.7 | 6.7 | 9020 | 8513 | 0 | 0 |
